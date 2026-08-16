"""One patient record per phone number, whichever door they came through.

The chat looked up an existing lead before creating one. The booking form did
not, so the same person booking twice from the website became two rows in the
CRM — three, in the case that prompted this — each with its own history, its own
attribution, and no way for reception to tell they were the same person.

A phone number is the identity a Vietnamese clinic actually uses: it is how they
ring back, how they find someone at the desk, and what the patient gives without
being asked twice. So it is the key here too.

The name is the interesting part. When a returning number gives a different one,
the newer answer wins: people correct typos, get married, or were entered by a
receptionist in a hurry the first time. The alternative — keeping whatever was
typed first, for ever — is what had a patient booking under "Popup Test" because
that is what someone typed into a test form weeks earlier.

A shared phone in a family is a real case this does not model. It needs patient
relations, not a heuristic, and guessing here would silently file a daughter's
appointment under her mother's name.
"""
from typing import Optional

from sqlalchemy.orm import Session

from backend.app.core import clock
from backend.app.models.models import PatientLead


def find_lead(db: Session, clinic_id: Optional[int], phone: Optional[str]) -> Optional[PatientLead]:
    """The existing patient with this number at this clinic, if any.

    Scoped to the clinic: two tenants sharing a phone number are two patients,
    and crossing that boundary would leak one clinic's records into another's.
    """
    if not phone or not clinic_id:
        return None
    return db.query(PatientLead).filter(
        PatientLead.phone == phone,
        PatientLead.clinic_id == clinic_id,
    ).first()


def upsert_lead(db: Session, clinic_id: Optional[int], full_name: str, phone: Optional[str],
                source: str, email: Optional[str] = None,
                referred_by_patient_id: Optional[int] = None,
                consent: bool = True) -> PatientLead:
    """Return the patient with this number, creating one only if new.

    Caller is responsible for flush/commit, so this composes with whatever
    transaction the endpoint is already running.
    """
    lead = find_lead(db, clinic_id, phone)
    if lead is None:
        lead = PatientLead(
            clinic_id=clinic_id, full_name=full_name, phone=phone, email=email,
            source=source, referred_by_patient_id=referred_by_patient_id,
        )
        db.add(lead)
    else:
        # Most recent self-identification wins; never blank out what is there.
        if full_name and full_name.strip() and full_name != lead.full_name:
            lead.full_name = full_name.strip()
        if email and not lead.email:
            lead.email = email

    if consent:
        lead.consent_given = True
        lead.consent_timestamp = clock.now()
    return lead
