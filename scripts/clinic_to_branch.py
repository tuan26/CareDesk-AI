"""Convert a Clinic into a Branch of another Clinic.

Early tenants were sometimes provisioned with one Clinic per physical location.
That is the wrong shape: Clinic is the billing/tenant boundary, so N locations
became N subscriptions, N price lists and N separate patient databases — a
patient visiting two locations shows up as two people, which breaks recall and
follow-up. Locations belong in Branch.

Usage (dry run prints the plan and changes nothing):

    python -m scripts.clinic_to_branch --source 2 --target 1
    python -m scripts.clinic_to_branch --source 2 --target 1 \
        --branch-name "Cơ sở Bạch Mai" --apply

Safety: dry run by default, backs the sqlite file up before writing, and
verifies the move afterwards. The source clinic is archived (is_active=False,
monthly_fee=0) rather than deleted, so it can be inspected — and un-archived —
before anyone removes the row for good.
"""
import argparse
import datetime
import shutil
import sys
from pathlib import Path

# Clinic names are Vietnamese and a Windows console often runs a legacy
# codepage; without this the script dies printing its own plan (same guard as
# backend/app/main.py).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.database import SessionLocal
from backend.app.core.slug import current_slug
from backend.app.models.models import (
    AISafetyRule, Appointment, AutomationRule, BookingRequest, Branch,
    ChannelIntegration, Clinic, Conversation, Doctor, DomainEvent, PatientLead,
    PatientPackage, Payment, RevenueRecord, ReviewRequest, ScheduledAction,
    Service, ServicePackage, SlugRegistry, User, WaitlistEntry,
)

# Everything scoped by clinic_id. Ordered so the report reads sensibly.
SCOPED_MODELS = [
    Branch, Doctor, Service, ServicePackage, User, PatientLead, Appointment,
    Conversation, PatientPackage, Payment, RevenueRecord, ReviewRequest,
    WaitlistEntry, BookingRequest, DomainEvent, ScheduledAction,
    ChannelIntegration, AISafetyRule,
]


def backup_sqlite() -> Path | None:
    url = settings.DATABASE_URL
    if not url.startswith("sqlite:///"):
        return None  # postgres/mysql: use pg_dump before running this
    src = Path(url[len("sqlite:///"):])
    if not src.exists():
        return None
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = src.with_name(f"{src.name}.bak_pre_clinic_to_branch_{stamp}")
    shutil.copy2(src, dst)
    return dst


def counts(db: Session, clinic_id: int) -> dict[str, int]:
    out = {}
    for model in SCOPED_MODELS:
        n = db.query(model).filter(model.clinic_id == clinic_id).count()
        if n:
            out[model.__name__] = n
    return out


def convert(db: Session, source_id: int, target_id: int,
            branch_name: str | None, apply: bool) -> int:
    source = db.query(Clinic).filter(Clinic.id == source_id).first()
    target = db.query(Clinic).filter(Clinic.id == target_id).first()
    if not source or not target:
        print("ERROR: source or target clinic not found")
        return 1
    if source_id == target_id:
        print("ERROR: source and target must differ")
        return 1
    if source.organization_id != target.organization_id:
        print(f"WARNING: different organizations "
              f"({source.organization_id} -> {target.organization_id}); "
              f"the public URL brand will change.")

    print(f"Source : #{source.id} {source.name!r}  fee={source.monthly_fee:,.0f} plan={source.plan}")
    print(f"Target : #{target.id} {target.name!r}")
    print(f"Moving : {counts(db, source_id)}")
    print()

    # --- Automation rules: never move a rule the target already has ---------
    # Both clinics get the same 8 seeded defaults. Moving them would leave the
    # target with two copies of every rule, so each patient would receive every
    # follow-up twice.
    target_rule_names = {
        r.name for r in db.query(AutomationRule).filter(AutomationRule.clinic_id == target_id)
    }
    dup_rules = (
        db.query(AutomationRule)
        .filter(AutomationRule.clinic_id == source_id,
                AutomationRule.name.in_(target_rule_names))
        .all()
    )
    if dup_rules:
        print(f"AutomationRule: dropping {len(dup_rules)} duplicate rule(s) "
              f"already present on the target (would double every follow-up)")

    # --- The branch this clinic becomes ------------------------------------
    primary = (
        db.query(Branch)
        .filter(Branch.clinic_id == source_id)
        .order_by(Branch.id)
        .first()
    )
    if primary and branch_name:
        print(f"Branch  : #{primary.id} {primary.name!r} -> {branch_name!r}")
    elif primary:
        print(f"Branch  : #{primary.id} {primary.name!r} (name unchanged)")
    else:
        print("WARNING: source clinic has no branch; nothing will represent it")

    # --- Duplicate services are reported, never dropped --------------------
    target_services = {
        (s.name.strip().lower(), s.price) for s in db.query(Service).filter(Service.clinic_id == target_id)
    }
    for s in db.query(Service).filter(Service.clinic_id == source_id):
        near = [t for t in target_services if t[1] == s.price]
        if near:
            print(f"NOTE    : service {s.name!r} ({s.price:,.0f}đ) looks like a duplicate "
                  f"of {near[0][0]!r} on the target — moved anyway, delete it by hand if unwanted")

    if not apply:
        print("\nDRY RUN — nothing written. Re-run with --apply to perform the move.")
        return 0

    backup = backup_sqlite()
    print(f"\nBackup  : {backup}" if backup else "\nBackup  : (non-sqlite, take one yourself)")

    for rule in dup_rules:
        db.delete(rule)
    db.flush()

    moved = {}
    for model in SCOPED_MODELS + [AutomationRule]:
        n = (
            db.query(model)
            .filter(model.clinic_id == source_id)
            .update({model.clinic_id: target_id}, synchronize_session=False)
        )
        if n:
            moved[model.__name__] = n
    db.flush()

    if primary and branch_name:
        primary.name = branch_name  # slug deliberately untouched: printed links survive

    # --- Keep the old clinic URL alive -------------------------------------
    # Point the retired clinic slug at the branch it became, so any link already
    # handed out for this clinic 301s to the new location page instead of 404ing.
    if primary:
        rows = (
            db.query(SlugRegistry)
            .filter(SlugRegistry.entity_type == "clinic", SlugRegistry.entity_id == source_id)
            .all()
        )
        for row in rows:
            row.entity_type = "branch"
            row.entity_id = primary.id
            row.is_active = False  # retired -> resolver 301s to the branch's live slug
        if rows:
            print(f"Slug    : {len(rows)} retired clinic slug(s) now 301 to "
                  f"/{current_slug(db, 'branch', primary.id)}")

    # --- Archive, don't delete ---------------------------------------------
    source.is_active = False
    source.monthly_fee = 0.0
    source.landing_enabled = False
    db.commit()

    print(f"Moved   : {moved}")
    print(f"Archived: clinic #{source_id} (is_active=False, monthly_fee=0)")

    leftover = counts(db, source_id)
    if leftover:
        print(f"VERIFY FAILED: rows still attached to the source clinic: {leftover}")
        return 1
    print("Verify  : OK — no rows left on the source clinic")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", type=int, required=True, help="clinic id to convert")
    p.add_argument("--target", type=int, required=True, help="clinic id to absorb it")
    p.add_argument("--branch-name", help="rename the resulting branch")
    p.add_argument("--apply", action="store_true", help="actually write (default: dry run)")
    args = p.parse_args()

    db = SessionLocal()
    try:
        return convert(db, args.source, args.target, args.branch_name, args.apply)
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
