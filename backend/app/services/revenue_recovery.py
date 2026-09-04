"""Detect money the clinic is leaving behind, and prove how much of it came back.

The rest of the product records what happened. This module records what should
have happened and did not: a patient overdue for a revisit, a course of
treatment abandoned, a package about to expire unused, a booking request nobody
rang back, a no-show never rebooked, a lead who asked the price and vanished.

Three decisions here are load-bearing, and all three are about not lying to the
owner. A product whose headline number is "₫186 triệu đang thất thoát" dies the
first time an owner checks it and finds it invented.

**Money already collected is not recoverable revenue.** An expiring package with
four unused sessions is not ₫8 triệu the clinic can win back — they were paid
for it. What is at risk is delivery and the repurchase after it. Those
opportunities carry ``value_kind = AT_RISK_DELIVERED`` and are reported in their
own bucket, never inside the recoverable headline. See :data:`VALUE_KIND`.

**Probability starts as a stated assumption and becomes a measurement.** Until a
clinic has resolved :data:`MIN_RESOLVED_FOR_OWN_RATE` opportunities of a type,
the number comes from :data:`BASE_RATES` — conservative, documented, and shown
in the UI as an assumption. After that it is that clinic's own observed
conversion. There is no model, and nothing pretends there is one.

**A holdout is what makes "recovered revenue" a claim rather than a boast.** A
tenth of opportunities are deliberately never contacted. Patients who were
coming back anyway come back in both groups; only the *difference* is work the
product did. Assignment is a stable hash rather than a coin flip, because
re-running detection nightly with a random holdout would reshuffle the groups
and destroy the comparison. Without enough holdout to be worth anything,
:func:`recovery_performance` reports ``measurable: False`` instead of a
flattering number.
"""
import hashlib
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from backend.app.core import clock
from backend.app.models.models import (
    Appointment, BookingRequest, Clinic, Conversation, DomainEvent, Message,
    PatientLead, PatientPackage, RevenueAction, RevenueOpportunity, RevenueRecord,
    Service, ServicePackage,
)

logger = logging.getLogger(__name__)

# --- the six detectors -------------------------------------------------------

OVERDUE_REVISIT = "overdue_revisit"
STALLED_PACKAGE = "stalled_package"
PACKAGE_EXPIRING = "package_expiring"
LOST_BOOKING = "lost_booking"
NO_SHOW_RECOVERY = "no_show_recovery"
HIGH_INTENT_LOST_LEAD = "high_intent_lost_lead"

ALL_TYPES = (OVERDUE_REVISIT, STALLED_PACKAGE, PACKAGE_EXPIRING,
             LOST_BOOKING, NO_SHOW_RECOVERY, HIGH_INTENT_LOST_LEAD)

TYPE_LABELS = {
    OVERDUE_REVISIT: "Quá hạn tái khám",
    STALLED_PACKAGE: "Liệu trình bỏ dở",
    PACKAGE_EXPIRING: "Gói sắp hết hạn",
    LOST_BOOKING: "Yêu cầu đặt lịch bị bỏ quên",
    NO_SHOW_RECOVERY: "Hủy / không đến, chưa đặt lại",
    HIGH_INTENT_LOST_LEAD: "Hỏi giá rồi im",
}

#: New revenue the clinic has not collected, versus service already paid for and
#: not yet delivered. Only NEW_REVENUE may appear in the recoverable headline.
NEW_REVENUE = "new_revenue"
AT_RISK_DELIVERED = "at_risk_delivered"

VALUE_KIND = {
    OVERDUE_REVISIT: NEW_REVENUE,
    LOST_BOOKING: NEW_REVENUE,
    NO_SHOW_RECOVERY: NEW_REVENUE,
    HIGH_INTENT_LOST_LEAD: NEW_REVENUE,
    # Both of these sit on a package the patient already paid for.
    STALLED_PACKAGE: AT_RISK_DELIVERED,
    PACKAGE_EXPIRING: AT_RISK_DELIVERED,
}

#: Starting assumptions, used only until a clinic has its own numbers. Chosen
#: low on purpose: an owner who is told 18% and gets 25% keeps using the
#: product, one told 60% who gets 25% stops trusting every other figure on the
#: screen. These are assumptions, not findings, and the API labels them as such.
BASE_RATES = {
    OVERDUE_REVISIT: 0.18,
    STALLED_PACKAGE: 0.30,
    PACKAGE_EXPIRING: 0.35,
    LOST_BOOKING: 0.25,
    NO_SHOW_RECOVERY: 0.20,
    HIGH_INTENT_LOST_LEAD: 0.10,
}

#: Below this many resolved opportunities, a clinic's own conversion rate is
#: noise — 3 out of 4 is not a 75% conversion rate.
MIN_RESOLVED_FOR_OWN_RATE = 20

# --- what the subscription fee means ----------------------------------------

UNCONFIGURED = "unconfigured"
PILOT_FREE = "pilot_free"
SPONSORED = "sponsored"
PAID = "paid"

PRICING_MODES = {
    UNCONFIGURED: "Chưa cấu hình phí",
    PILOT_FREE: "Pilot miễn phí",
    SPONSORED: "Được tài trợ",
    PAID: "Có trả phí",
}

PILOT_STATUSES = {
    "none": "Không chạy pilot",
    "active": "Đang chạy pilot",
    "completed": "Pilot đã kết thúc",
}

#: Why an ROI figure is absent. A bare null reads as a bug; each of these reads
#: as a fact about the clinic, and only the last one is about missing data.
ROI_OK = "ok"
ROI_PILOT_FREE = "pilot_free"
ROI_SPONSORED = "sponsored"
ROI_NO_PRICE = "unconfigured_pricing"
ROI_NO_HOLDOUT = "insufficient_holdout"

# --- attribution ------------------------------------------------------------

DIRECT = "direct"
ASSISTED = "assisted"
ORGANIC = "organic"
UNKNOWN = "unknown"

ATTRIBUTION_LABELS = {
    DIRECT: "Trực tiếp",
    ASSISTED: "Gián tiếp",
    ORGANIC: "Tự quay lại",
    UNKNOWN: "Không xác định",
}

#: Booked within this many days of first contact: the message is the
#: straightforward explanation.
DIRECT_WINDOW_DAYS = 3
#: Past this a booking is not attributable to a message at all. Without a
#: ceiling every patient who ever returns eventually credits some opportunity,
#: and recovered revenue grows on its own.
ATTRIBUTION_WINDOW_DAYS = 30

#: Share of opportunities deliberately left uncontacted, to measure lift.
HOLDOUT_RATE = 0.10
#: Below this, the holdout cannot support a claim and none is made.
MIN_HOLDOUT_FOR_MEASUREMENT = 30

# Detection windows.
LOST_BOOKING_AFTER_DAYS = 2        # a request older than this was not followed up
NO_SHOW_REBOOK_WINDOW_DAYS = 14    # no rebooking within this = lost
LOST_LEAD_AFTER_DAYS = 7           # asked the price and went quiet
PACKAGE_EXPIRING_WITHIN_DAYS = 30
PACKAGE_STALLED_AFTER_DAYS = 45
#: Past this, someone is not "overdue", they have moved on. Chasing them reads
#: as spam and costs the clinic its Zalo OA more than it earns.
MAX_OVERDUE_DAYS = 365

#: Closed list. Free-text loss reasons are unusable in aggregate, and the whole
#: point of asking is to see which reason repeats.
LOSS_REASONS = {
    "price": "Chê giá cao",
    "timing": "Chưa sắp xếp được thời gian",
    "competitor": "Đã làm ở nơi khác",
    "unhappy": "Không hài lòng lần trước",
    "no_need": "Không còn nhu cầu",
    "unreachable": "Không liên lạc được",
    "no_show": "Đặt lịch rồi không đến",
    "wrong_target": "Không đúng đối tượng",
}


# --- small helpers -----------------------------------------------------------

def _naive(value: Optional[datetime]) -> Optional[datetime]:
    """Timestamps arrive tz-aware from Postgres and naive from SQLite."""
    if value is None:
        return None
    return value.replace(tzinfo=None) if value.tzinfo else value


def _days_between(later: datetime, earlier: datetime) -> int:
    return max(0, (later - earlier).days)


def assign_holdout(clinic_id: int, patient_id: int, opportunity_type: str) -> bool:
    """Stable, not random.

    Detection re-runs nightly. A coin flip would move a patient in and out of the
    holdout between runs, so neither group would mean anything by the time
    anyone read the report. Hashing the identity keeps a patient on the same
    side of the experiment for as long as the opportunity exists.
    """
    key = f"{clinic_id}:{patient_id}:{opportunity_type}".encode()
    bucket = int(hashlib.sha256(key).hexdigest()[:8], 16) % 100
    return bucket < int(HOLDOUT_RATE * 100)


def observed_rate(db: Session, clinic_id: int, opportunity_type: str) -> tuple[float, bool]:
    """This clinic's own conversion for a type, or the base rate.

    Returns (rate, is_measured). ``is_measured`` is what the UI needs to stop
    presenting an assumption as a finding.
    """
    resolved = db.query(
        func.count(RevenueOpportunity.id),
        func.sum(case((RevenueOpportunity.status == "recovered", 1), else_=0)),
    ).filter(
        RevenueOpportunity.clinic_id == clinic_id,
        RevenueOpportunity.opportunity_type == opportunity_type,
        RevenueOpportunity.status.in_(("recovered", "lost")),
        RevenueOpportunity.is_holdout == False,  # noqa: E712
    ).one()

    total, recovered = int(resolved[0] or 0), int(resolved[1] or 0)
    if total < MIN_RESOLVED_FOR_OWN_RATE:
        return BASE_RATES.get(opportunity_type, 0.15), False
    return recovered / total, True


def _clinic_average_ticket(db: Session, clinic_id: int) -> float:
    """What a visit is worth here, from revenue actually recorded.

    Falls back to the mean service price, and to 0 when the clinic has neither —
    a zero-value opportunity sorts to the bottom of the queue, which is the
    right place for one we cannot size.
    """
    avg = db.query(func.avg(RevenueRecord.amount)).filter(
        RevenueRecord.clinic_id == clinic_id, RevenueRecord.amount > 0
    ).scalar()
    if avg:
        return float(avg)
    avg_price = db.query(func.avg(Service.price)).filter(
        Service.clinic_id == clinic_id, Service.price > 0
    ).scalar()
    return float(avg_price or 0.0)


def _package_unit_value(pp: PatientPackage) -> float:
    """Value of one unused session, from what the patient actually paid."""
    if not pp.sessions_total:
        return 0.0
    return float(pp.amount_paid or 0.0) / pp.sessions_total


def score(opportunity: RevenueOpportunity) -> float:
    """Money Queue ordering: value × probability × urgency.

    Urgency is not "how long ago" — it is "how much does acting today beat
    acting next week". A package expiring on Friday is urgent; a revisit six
    months overdue is not urgent, it is nearly dead, and the weight says so.
    """
    return float(opportunity.estimated_value or 0) * float(opportunity.probability or 0) \
        * _urgency_weight(opportunity.opportunity_type, opportunity.urgency_days)


def _urgency_weight(opportunity_type: str, urgency_days: int) -> float:
    if opportunity_type == PACKAGE_EXPIRING:
        # Counts down: fewer days left, more urgent.
        if urgency_days <= 7:
            return 2.0
        if urgency_days <= 14:
            return 1.5
        return 1.0
    # Everything else counts up, and decays.
    if urgency_days <= 14:
        return 1.5
    if urgency_days <= 45:
        return 1.2
    if urgency_days <= 120:
        return 1.0
    return 0.6


# --- probability -------------------------------------------------------------

def _probability(db: Session, clinic_id: int, opportunity_type: str,
                 patient: PatientLead, urgency_days: int) -> tuple[float, List[Dict[str, Any]]]:
    """A base rate, adjusted by things that are actually observable.

    Every adjustment returns its own explanation. A number on a screen that
    cannot say where it came from does not get acted on twice.
    """
    rate, measured = observed_rate(db, clinic_id, opportunity_type)
    reasons: List[Dict[str, Any]] = [{
        "code": "base_rate",
        "text": (f"Tỷ lệ thực tế của phòng khám cho nhóm này: {rate:.0%}" if measured
                 else f"Giả định khởi điểm {rate:.0%} (chưa đủ dữ liệu thực tế của phòng khám)"),
        "weight": rate,
        "measured": measured,
    }]

    def adjust(factor: float, code: str, text: str):
        nonlocal rate
        rate *= factor
        reasons.append({"code": code, "text": text, "weight": factor, "measured": True})

    if not patient.phone:
        adjust(0.30, "no_phone", "Không có số điện thoại — gần như không tiếp cận được")
    if patient.consent_given:
        adjust(1.15, "consent", "Khách đã đồng ý nhận liên hệ")

    completed = db.query(func.count(Appointment.id)).filter(
        Appointment.patient_id == patient.id, Appointment.status == "completed"
    ).scalar() or 0
    if completed >= 2:
        adjust(1.30, "loyal", f"Đã đến khám {completed} lần — khách quen")
    elif completed == 0:
        adjust(0.70, "never_visited", "Chưa từng đến khám lần nào")

    if urgency_days > 180 and opportunity_type != PACKAGE_EXPIRING:
        adjust(0.60, "stale", f"Đã {urgency_days} ngày — càng để lâu càng khó kéo lại")

    # Contact fatigue: someone chased twice this month is not chased a third time
    # with the same expectation.
    recent_contacts = db.query(func.count(RevenueOpportunity.id)).filter(
        RevenueOpportunity.patient_id == patient.id,
        RevenueOpportunity.contacted_at != None,  # noqa: E711
        RevenueOpportunity.contacted_at >= clock.now() - timedelta(days=30),
    ).scalar() or 0
    if recent_contacts >= 2:
        adjust(0.70, "fatigue", f"Đã nhắn {recent_contacts} lần trong 30 ngày qua")

    # Never 0, never a certainty.
    return max(0.02, min(0.85, rate)), reasons


# --- next best action --------------------------------------------------------

def _channel_for(db: Session, clinic_id: int, patient: PatientLead) -> str:
    """Zalo where we have an id for them, SMS where we have a phone, else a call.

    Deliberately does not invent a channel the clinic has not connected — the
    gateway would only fail later, and a queue full of undeliverable actions is
    worse than one that says "gọi điện".
    """
    from backend.app.services import channel_gateway

    if patient.external_id and channel_gateway.get_integration(db, clinic_id, "zalo"):
        return "zalo"
    if patient.phone:
        return "sms"
    return "call"


#: Anything a receptionist typed after the name to tell two records apart —
#: "(tên mới)", "[Zalo]", "- khách cũ". Harmless in a list, humiliating in a
#: greeting: taking the last word of "Trịnh Thị Hoa (tên mới)" opens the message
#: with "Chào mới)".
_NAME_SUFFIX = re.compile(r"[(\[{].*?[)\]}]|[-–—,].*$", re.S)


def _first_name(full_name: Optional[str]) -> str:
    """The Vietnamese given name — the last word, once the noise is gone.

    Falls back to "anh/chị" rather than to a fragment. A message that opens
    "Chào anh/chị" is merely impersonal; one that opens "Chào mới)" tells the
    patient they are a row in a database.
    """
    if not full_name:
        return "anh/chị"
    cleaned = _NAME_SUFFIX.sub(" ", full_name)
    words = [w for w in cleaned.split() if any(c.isalpha() for c in w)]
    return words[-1] if words else "anh/chị"


def _message_for(opportunity_type: str, clinic: Clinic, patient: PatientLead,
                 service_name: Optional[str], detail: Dict[str, Any]) -> str:
    """A draft, never a send.

    Staff read and edit this before it goes anywhere. No offer or discount is
    ever written in here — the product does not get to give away a clinic's
    margin, and a template that promises "giảm 20%" would do exactly that at
    scale.
    """
    name = _first_name(patient.full_name)
    brand = clinic.name if clinic else "phòng khám"
    what = service_name or "dịch vụ đã làm"

    if opportunity_type == OVERDUE_REVISIT:
        return (f"Chào {name}, {brand} thấy đã đến lịch tái khám {what} của mình rồi ạ. "
                f"Mình sắp xếp được buổi nào trong tuần này để bên em giữ chỗ trước không ạ?")
    if opportunity_type in (STALLED_PACKAGE, PACKAGE_EXPIRING):
        left = detail.get("sessions_left", 0)
        when = detail.get("expires_label")
        tail = f" Gói của mình còn hạn đến {when}." if when else ""
        return (f"Chào {name}, liệu trình {what} của mình còn {left} buổi chưa dùng ạ.{tail} "
                f"Mình muốn đặt buổi tiếp theo vào lúc nào để em xếp lịch ạ?")
    if opportunity_type == LOST_BOOKING:
        return (f"Chào {name}, {brand} nhận được yêu cầu đặt lịch {what} của mình nhưng "
                f"chưa liên hệ lại được ạ. Mình còn nhu cầu thì cho em xin khung giờ thuận tiện nhé.")
    if opportunity_type == NO_SHOW_RECOVERY:
        return (f"Chào {name}, lịch {what} hôm trước của mình chưa thực hiện được ạ. "
                f"Mình muốn dời sang buổi nào thì nhắn em, em giữ chỗ lại cho mình nhé.")
    if opportunity_type == HIGH_INTENT_LOST_LEAD:
        return (f"Chào {name}, trước đó mình có hỏi {brand} về {what} ạ. "
                f"Mình cần em tư vấn thêm gì không, hay muốn đặt một buổi khám để bác sĩ xem trực tiếp ạ?")
    return f"Chào {name}, {brand} liên hệ lại với mình ạ."


# --- detection ---------------------------------------------------------------

def _upsert(db: Session, clinic_id: int, patient: PatientLead, opportunity_type: str,
            dedupe_key: str, value: float, urgency_days: int, clinic: Clinic,
            service_name: Optional[str] = None, detail: Optional[Dict[str, Any]] = None,
            **links: Any) -> Optional[RevenueOpportunity]:
    """Create or refresh one opportunity.

    Refresh rather than replace: an opportunity a receptionist has already acted
    on keeps its status and its holdout side. Only the figures move, because the
    package is a day closer to expiry than it was yesterday.
    """
    detail = detail or {}
    existing = db.query(RevenueOpportunity).filter(
        RevenueOpportunity.clinic_id == clinic_id,
        RevenueOpportunity.opportunity_type == opportunity_type,
        RevenueOpportunity.patient_id == patient.id,
        RevenueOpportunity.dedupe_key == dedupe_key,
    ).first()

    # Anything already dealt with stays dealt with.
    if existing and existing.status not in ("open",):
        return None

    probability, reasons = _probability(db, clinic_id, opportunity_type, patient, urgency_days)

    if existing:
        existing.estimated_value = value
        existing.probability = probability
        existing.urgency_days = urgency_days
        existing.reasons = reasons
        return existing

    opportunity = RevenueOpportunity(
        clinic_id=clinic_id,
        patient_id=patient.id,
        opportunity_type=opportunity_type,
        dedupe_key=dedupe_key,
        estimated_value=value,
        probability=probability,
        urgency_days=urgency_days,
        reasons=reasons,
        recommended_channel=_channel_for(db, clinic_id, patient),
        recommended_message=_message_for(opportunity_type, clinic, patient, service_name, detail),
        recommended_offer=None,  # the clinic's margin is not ours to spend
        is_holdout=assign_holdout(clinic_id, patient.id, opportunity_type),
        status="open",
        **links,
    )
    db.add(opportunity)
    return opportunity


def _has_upcoming_appointment(db: Session, patient_id: int, now: datetime) -> bool:
    appt = db.query(Appointment).filter(
        Appointment.patient_id == patient_id,
        Appointment.status.in_(("pending", "awaiting_deposit", "confirmed")),
    ).order_by(Appointment.start_time.desc()).first()
    return bool(appt and _naive(appt.start_time) >= now)


def detect_overdue_revisits(db: Session, clinic_id: int, clinic: Clinic) -> int:
    """A completed visit for a service with a revisit interval, now past due.

    Services with no interval are skipped entirely. That is the difference
    between a recall system and a nuisance: the clinic states which treatments
    repeat and how often, and nothing is chased that they did not say repeats.
    """
    now = clock.now()
    found = 0

    services = {s.id: s for s in db.query(Service).filter(
        Service.clinic_id == clinic_id,
        Service.revisit_interval_days != None,  # noqa: E711
        Service.revisit_interval_days > 0,
    ).all()}
    if not services:
        return 0

    # Latest completed visit per (patient, service).
    rows = db.query(
        Appointment.patient_id, Appointment.service_id,
        func.max(Appointment.start_time).label("last_visit"),
    ).filter(
        Appointment.clinic_id == clinic_id,
        Appointment.status == "completed",
        Appointment.service_id.in_(services.keys()),
    ).group_by(Appointment.patient_id, Appointment.service_id).all()

    for patient_id, service_id, last_visit in rows:
        service = services[service_id]
        last = _naive(last_visit)
        if not last:
            continue
        due = last + timedelta(days=service.revisit_interval_days)
        if due > now:
            continue
        overdue = _days_between(now, due)
        if overdue > MAX_OVERDUE_DAYS:
            continue
        if _has_upcoming_appointment(db, patient_id, now):
            continue

        patient = db.get(PatientLead, patient_id)
        if not patient:
            continue
        if _upsert(db, clinic_id, patient, OVERDUE_REVISIT, dedupe_key=str(service_id),
                   value=float(service.price or 0.0), urgency_days=overdue, clinic=clinic,
                   service_name=service.name, service_id=service_id):
            found += 1
    return found


def detect_package_opportunities(db: Session, clinic_id: int, clinic: Clinic) -> int:
    """Expiring first, stalled second — a package is never both.

    Both carry AT_RISK_DELIVERED: the clinic has the money already. What is at
    stake is a patient who paid and did not get what they paid for, which is a
    refund conversation and a review, not a sale.
    """
    now = clock.now()
    found = 0

    packages = db.query(PatientPackage).filter(
        PatientPackage.clinic_id == clinic_id,
        PatientPackage.status == "active",
        PatientPackage.sessions_used < PatientPackage.sessions_total,
    ).all()

    for pp in packages:
        patient = db.get(PatientLead, pp.patient_id)
        if not patient:
            continue
        sessions_left = (pp.sessions_total or 0) - (pp.sessions_used or 0)
        value = _package_unit_value(pp) * sessions_left
        package = db.get(ServicePackage, pp.package_id) if pp.package_id else None
        name = package.name if package else "liệu trình"
        expires = _naive(pp.expires_at)

        if expires and expires >= now and _days_between(expires, now) <= PACKAGE_EXPIRING_WITHIN_DAYS:
            days_left = _days_between(expires, now)
            if _upsert(db, clinic_id, patient, PACKAGE_EXPIRING, dedupe_key=str(pp.id),
                       value=value, urgency_days=days_left, clinic=clinic, service_name=name,
                       detail={"sessions_left": sessions_left,
                               "expires_label": expires.strftime("%d/%m/%Y")},
                       patient_package_id=pp.id):
                found += 1
            continue

        last = db.query(func.max(Appointment.start_time)).filter(
            Appointment.patient_id == pp.patient_id,
            Appointment.status == "completed",
        ).scalar()
        since = _days_between(now, _naive(last)) if last else _days_between(now, _naive(pp.purchased_at) or now)
        if since < PACKAGE_STALLED_AFTER_DAYS:
            continue
        if _has_upcoming_appointment(db, pp.patient_id, now):
            continue
        if _upsert(db, clinic_id, patient, STALLED_PACKAGE, dedupe_key=str(pp.id),
                   value=value, urgency_days=since, clinic=clinic, service_name=name,
                   detail={"sessions_left": sessions_left},
                   patient_package_id=pp.id):
            found += 1
    return found


def detect_lost_bookings(db: Session, clinic_id: int, clinic: Clinic) -> int:
    """Someone asked for an appointment and never got one.

    The most embarrassing row on the whole dashboard, and the cheapest to fix:
    the patient already said yes.
    """
    now = clock.now()
    cutoff = now - timedelta(days=LOST_BOOKING_AFTER_DAYS)
    found = 0

    requests = db.query(BookingRequest).filter(
        BookingRequest.clinic_id == clinic_id,
        BookingRequest.status.in_(("requested", "contacted")),
        BookingRequest.created_at <= cutoff,
        BookingRequest.patient_id != None,  # noqa: E711
    ).all()

    for req in requests:
        patient = db.get(PatientLead, req.patient_id)
        if not patient:
            continue
        if _has_upcoming_appointment(db, req.patient_id, now):
            continue
        service = db.get(Service, req.service_id) if req.service_id else None
        value = float(service.price) if service and service.price else _clinic_average_ticket(db, clinic_id)
        waiting = _days_between(now, _naive(req.created_at) or now)
        if _upsert(db, clinic_id, patient, LOST_BOOKING, dedupe_key=str(req.id),
                   value=value, urgency_days=waiting, clinic=clinic,
                   service_name=service.name if service else req.service_or_need,
                   booking_request_id=req.id, service_id=req.service_id):
            found += 1
    return found


def detect_no_show_recovery(db: Session, clinic_id: int, clinic: Clinic) -> int:
    """Cancelled or did not turn up, and has not rebooked since."""
    now = clock.now()
    found = 0

    misses = db.query(Appointment).filter(
        Appointment.clinic_id == clinic_id,
        Appointment.status.in_(("cancelled", "no_show")),
        Appointment.start_time <= now,
        Appointment.start_time >= now - timedelta(days=MAX_OVERDUE_DAYS),
    ).all()

    seen: set[int] = set()
    for appt in misses:
        if appt.patient_id in seen:
            continue
        since = _days_between(now, _naive(appt.start_time) or now)
        if since < NO_SHOW_REBOOK_WINDOW_DAYS:
            continue  # still inside the window where they might rebook themselves

        rebooked = db.query(Appointment).filter(
            Appointment.patient_id == appt.patient_id,
            Appointment.start_time > appt.start_time,
            Appointment.status.in_(("pending", "awaiting_deposit", "confirmed", "completed")),
        ).first()
        if rebooked:
            continue

        patient = db.get(PatientLead, appt.patient_id)
        if not patient:
            continue
        seen.add(appt.patient_id)
        service = db.get(Service, appt.service_id) if appt.service_id else None
        value = float(service.price) if service and service.price else _clinic_average_ticket(db, clinic_id)
        if _upsert(db, clinic_id, patient, NO_SHOW_RECOVERY, dedupe_key=str(appt.id),
                   value=value, urgency_days=since, clinic=clinic,
                   service_name=service.name if service else None,
                   appointment_id=appt.id, service_id=appt.service_id):
            found += 1
    return found


def detect_high_intent_lost_leads(db: Session, clinic_id: int, clinic: Clinic) -> int:
    """Asked what it costs, then went quiet, and never booked anything.

    Intent is taken from the price_asked event the chat already emits, not
    guessed from message text — the engine does not get a second opinion on what
    the conversation meant.
    """
    now = clock.now()
    cutoff = now - timedelta(days=LOST_LEAD_AFTER_DAYS)
    found = 0

    asks = db.query(
        DomainEvent.patient_id, func.max(DomainEvent.created_at).label("asked_at"),
    ).filter(
        DomainEvent.clinic_id == clinic_id,
        DomainEvent.event_type == "price_asked",
        DomainEvent.patient_id != None,  # noqa: E711
        DomainEvent.created_at <= cutoff,
    ).group_by(DomainEvent.patient_id).all()

    average = _clinic_average_ticket(db, clinic_id)

    for patient_id, asked_at in asks:
        ever_booked = db.query(Appointment.id).filter(
            Appointment.patient_id == patient_id
        ).first()
        if ever_booked:
            continue
        patient = db.get(PatientLead, patient_id)
        if not patient:
            continue
        silent = _days_between(now, _naive(asked_at) or now)
        if silent > MAX_OVERDUE_DAYS:
            continue

        # What they asked about, if the conversation recorded it.
        conversation = db.query(Conversation).filter(
            Conversation.patient_id == patient_id
        ).order_by(Conversation.id.desc()).first()
        service_name = None
        if conversation and isinstance(conversation.booking_state, dict):
            sid = conversation.booking_state.get("service_id")
            if sid:
                service = db.get(Service, sid)
                service_name = service.name if service else None

        if _upsert(db, clinic_id, patient, HIGH_INTENT_LOST_LEAD, dedupe_key="",
                   value=average, urgency_days=silent, clinic=clinic,
                   service_name=service_name or "dịch vụ mình quan tâm"):
            found += 1
    return found


def _match_strength(opportunity: RevenueOpportunity, appointment: Appointment) -> tuple:
    """Which of a patient's open opportunities gets to claim one booking.

    Ordered by how defensible the claim is, not by how much it is worth —
    picking the most valuable would quietly bias every recovery figure upwards.
    Fully deterministic, so the same booking never flips between opportunities
    on a later pass.
    """
    same_service = opportunity.service_id is not None and \
        opportunity.service_id == appointment.service_id
    contacted = opportunity.contacted_at is not None
    when = _naive(opportunity.contacted_at) or _naive(opportunity.detected_at) or datetime.min
    return (same_service, contacted, when, opportunity.id)


def _classify(opportunity: RevenueOpportunity, booked_at: datetime) -> str:
    """Direct, assisted, organic or unknown — how honest the credit is.

    A patient nobody contacted who books anyway is ``organic``: the baseline the
    holdout exists to measure, and never revenue the product may claim. A
    booking landing months after the only message is ``unknown``, because at
    that distance the message is a story rather than a cause.
    """
    contacted = _naive(opportunity.contacted_at)
    if not contacted:
        return ORGANIC
    gap = (booked_at - contacted).days
    if gap < 0:
        # Booked before anyone wrote to them. Whatever brought them in, not us.
        return ORGANIC
    if gap <= DIRECT_WINDOW_DAYS:
        return DIRECT
    if gap <= ATTRIBUTION_WINDOW_DAYS:
        return ASSISTED
    return UNKNOWN


def _settle_booked(db: Session, clinic_id: int) -> int:
    """Move bookings on to whatever actually happened to them.

    This is where "recovered" earns its name. An opportunity stays ``booked``
    until the visit is completed *and* revenue exists for it; a booking that was
    cancelled or no-showed goes to ``lost``, not quietly back to open. The
    amount is always money that was recorded, never the estimate — the estimate
    is what we hoped for, and putting it in the recovered column is how a
    dashboard ends up disagreeing with the bank.
    """
    now = clock.now()
    settled = 0

    for opportunity in db.query(RevenueOpportunity).filter(
        RevenueOpportunity.clinic_id == clinic_id,
        RevenueOpportunity.status == "booked",
        RevenueOpportunity.resolved_appointment_id != None,  # noqa: E711
    ).all():
        appointment = db.get(Appointment, opportunity.resolved_appointment_id)
        if not appointment:
            continue

        if appointment.status in ("cancelled", "no_show"):
            opportunity.status = "lost"
            opportunity.loss_reason = "no_show"
            opportunity.resolved_at = now
            settled += 1
            continue

        if appointment.status != "completed":
            continue

        record = db.query(RevenueRecord).filter(
            RevenueRecord.appointment_id == appointment.id
        ).order_by(RevenueRecord.id.asc()).first()

        opportunity.status = "recovered"
        opportunity.resolved_at = now
        if record:
            opportunity.recovered_amount = float(record.amount or 0)
            opportunity.resolved_revenue_record_id = record.id
        else:
            # Completed against a package the patient had already paid for. The
            # visit happened and the opportunity is genuinely recovered, but it
            # brought in no new money and must not pretend otherwise.
            opportunity.recovered_amount = 0.0
        settled += 1

    return settled


def _credit_new_bookings(db: Session, clinic_id: int) -> int:
    """Tie each new booking to exactly one opportunity.

    The bug this replaces: a patient overdue for a revisit who had also left a
    booking request and once no-showed carried three open opportunities, and a
    single 2.000.000d appointment closed all three as recovered — 6.000.000d on
    the dashboard for one visit. One booking is one recovery. The others were
    real misses, so they are not deleted; they are marked ``superseded`` and
    left out of both the revenue and the conversion maths.
    """
    now = clock.now()
    credited = 0

    live = db.query(RevenueOpportunity).filter(
        RevenueOpportunity.clinic_id == clinic_id,
        RevenueOpportunity.status.in_(("open", "contacted")),
    ).all()

    by_patient: Dict[int, List[RevenueOpportunity]] = {}
    for opportunity in live:
        by_patient.setdefault(opportunity.patient_id, []).append(opportunity)

    for patient_id, opportunities in by_patient.items():
        earliest = min((_naive(o.detected_at) or now) for o in opportunities)
        appointment = db.query(Appointment).filter(
            Appointment.patient_id == patient_id,
            Appointment.created_at >= earliest,
            Appointment.status.in_(("pending", "awaiting_deposit", "confirmed", "completed")),
        ).order_by(Appointment.id.asc()).first()
        if not appointment:
            continue

        booked_at = _naive(appointment.created_at) or now
        # An opportunity detected after the booking was made cannot have caused
        # it, and stays open — the patient may still owe that visit.
        eligible = [o for o in opportunities if (_naive(o.detected_at) or now) <= booked_at]
        if not eligible:
            continue

        winner = max(eligible, key=lambda o: _match_strength(o, appointment))
        winner.status = "booked"
        winner.booked_at = booked_at
        winner.resolved_appointment_id = appointment.id
        winner.attribution_class = _classify(winner, booked_at)
        credited += 1

        for other in eligible:
            if other.id == winner.id:
                continue
            other.status = "superseded"
            other.resolved_at = now
            other.resolved_appointment_id = appointment.id

    return credited


def detect_responses(db: Session, clinic_id: int) -> int:
    """Mark an action answered when the patient actually wrote back.

    Read from their own messages rather than asked of staff: "did they reply" is
    the one funnel step nobody remembers to record, and an unrecorded reply
    makes every message look ignored.
    """
    answered = 0
    pending = db.query(RevenueAction).filter(
        RevenueAction.clinic_id == clinic_id,
        RevenueAction.status == "sent",
    ).all()

    for action in pending:
        opportunity = db.get(RevenueOpportunity, action.opportunity_id)
        if not opportunity:
            continue
        sent_at = _naive(action.created_at)
        if not sent_at:
            continue
        reply = db.query(Message).join(
            Conversation, Message.conversation_id == Conversation.id
        ).filter(
            Conversation.patient_id == opportunity.patient_id,
            Message.sender == "user",
            Message.created_at >= sent_at,
        ).order_by(Message.id.asc()).first()
        if not reply:
            continue
        action.status = "responded"
        action.responded_at = _naive(reply.created_at)
        answered += 1

    return answered


def record_action(db: Session, opportunity: RevenueOpportunity, channel: str,
                  message: Optional[str] = None, template_code: Optional[str] = None,
                  user_id: Optional[int] = None) -> RevenueAction:
    """Log that a human reached out. Sends nothing."""
    action = RevenueAction(
        clinic_id=opportunity.clinic_id, opportunity_id=opportunity.id,
        channel=channel, template_code=template_code,
        message=message if message is not None else opportunity.recommended_message,
        created_by_user_id=user_id, status="sent",
    )
    db.add(action)
    if opportunity.status == "open":
        opportunity.status = "contacted"
    # First contact is what attribution measures from; later nudges do not
    # restart the clock and make an old lead look freshly won.
    if opportunity.contacted_at is None:
        opportunity.contacted_at = clock.now()
    return action


def run_detection(db: Session, clinic_id: int) -> Dict[str, int]:
    """The nightly sweep. Idempotent: running it twice changes nothing."""
    clinic = db.get(Clinic, clinic_id)
    if not clinic:
        return {}

    # Attribution runs before detection, in this order on purpose. Settling
    # first means a visit that already happened is credited to the opportunity
    # that was waiting for it, instead of being detected all over again as a
    # fresh miss on the next line.
    result = {
        "settled": _settle_booked(db, clinic_id),
        "credited": _credit_new_bookings(db, clinic_id),
        "responded": detect_responses(db, clinic_id),
    }
    result[OVERDUE_REVISIT] = detect_overdue_revisits(db, clinic_id, clinic)
    packages = detect_package_opportunities(db, clinic_id, clinic)
    result[PACKAGE_EXPIRING] = packages  # split reported per-type by the API
    result[LOST_BOOKING] = detect_lost_bookings(db, clinic_id, clinic)
    result[NO_SHOW_RECOVERY] = detect_no_show_recovery(db, clinic_id, clinic)
    result[HIGH_INTENT_LOST_LEAD] = detect_high_intent_lost_leads(db, clinic_id, clinic)
    db.commit()
    logger.info("Revenue detection cho clinic %s: %s", clinic_id, result)
    return result


# --- reporting ---------------------------------------------------------------

def leakage_summary(db: Session, clinic_id: int) -> Dict[str, Any]:
    """The headline. Recoverable and already-paid are never added together."""
    rows = db.query(
        RevenueOpportunity.opportunity_type,
        func.count(RevenueOpportunity.id),
        func.sum(RevenueOpportunity.estimated_value),
        func.sum(RevenueOpportunity.estimated_value * RevenueOpportunity.probability),
    ).filter(
        RevenueOpportunity.clinic_id == clinic_id,
        RevenueOpportunity.status == "open",
        RevenueOpportunity.is_holdout == False,  # noqa: E712
    ).group_by(RevenueOpportunity.opportunity_type).all()

    buckets = []
    recoverable = weighted = at_risk = 0.0
    for opportunity_type, count, gross, weighted_value in rows:
        gross, weighted_value = float(gross or 0), float(weighted_value or 0)
        kind = VALUE_KIND.get(opportunity_type, NEW_REVENUE)
        _, measured = observed_rate(db, clinic_id, opportunity_type)
        buckets.append({
            "type": opportunity_type,
            "label": TYPE_LABELS.get(opportunity_type, opportunity_type),
            "value_kind": kind,
            "count": int(count or 0),
            "gross_value": gross,
            "expected_value": weighted_value,
            "probability_is_measured": measured,
        })
        if kind == NEW_REVENUE:
            recoverable += gross
            weighted += weighted_value
        else:
            at_risk += gross

    buckets.sort(key=lambda b: b["expected_value"], reverse=True)
    return {
        # Money not yet collected, that could still be.
        "recoverable_gross": recoverable,
        # The same money after multiplying by how likely each one is. This is
        # the number to plan with; the gross is the ceiling, not a forecast.
        "recoverable_expected": weighted,
        # Already paid for, not yet delivered. Deliberately outside the total.
        "at_risk_delivered": at_risk,
        "buckets": buckets,
    }


#: Statuses meaning the patient came back. Booked is not yet money, but it is
#: unambiguously a return, which is what a conversion rate measures.
_CONVERTED = ("booked", "recovered")


def recovery_performance(db: Session, clinic_id: int, days: int = 90) -> Dict[str, Any]:
    """What CareDesk can honestly claim, measured against the holdout.

    ``gross_recovered`` is money recorded against every contacted opportunity
    that converted. Some of those patients were coming back regardless, so that
    figure flatters the product and is labelled as such.

    ``net_attributable`` is the part the holdout says would not have happened
    otherwise. When the holdout is too small to mean anything the field is None
    and ``measurable`` is False — no estimate is offered in its place, because
    an unmeasurable claim dressed up as a measured one is the failure mode this
    whole design exists to avoid.

    ``superseded`` opportunities are excluded from both sides. They are the
    other misses belonging to a patient whose single booking was already
    credited elsewhere; counting them as won would inflate the rate, counting
    them as lost would deflate it, and they are evidence of neither.
    """
    since = clock.now() - timedelta(days=days)
    base = db.query(RevenueOpportunity).filter(
        RevenueOpportunity.clinic_id == clinic_id,
        RevenueOpportunity.detected_at >= since,
        RevenueOpportunity.status != "superseded",
    )

    def split(is_holdout: bool):
        rows = base.filter(RevenueOpportunity.is_holdout == is_holdout).all()
        # The holdout is never contacted, so its denominator is everything
        # detected; the treated group's is everything actually reached.
        eligible = [o for o in rows if is_holdout or o.contacted_at is not None]
        won = [o for o in eligible if o.status in _CONVERTED]
        # Money, not bookings: only a completed visit with a revenue record has
        # an amount, and everything else contributes zero rather than its hope.
        amount = sum(float(o.recovered_amount or 0) for o in eligible
                     if o.status == "recovered")
        return len(eligible), len(won), amount

    treated_n, treated_won, treated_amount = split(False)
    holdout_n, holdout_won, _ = split(True)

    treated_rate = treated_won / treated_n if treated_n else 0.0
    holdout_rate = holdout_won / holdout_n if holdout_n else 0.0
    average_win = treated_amount / treated_won if treated_won else 0.0

    measurable = holdout_n >= MIN_HOLDOUT_FOR_MEASUREMENT and treated_n > 0
    lift = treated_rate - holdout_rate if measurable else None
    net = max(0.0, lift * treated_n * average_win) if measurable else None

    clinic = db.get(Clinic, clinic_id)
    fee = float(clinic.monthly_fee or 0) * (days / 30.0) if clinic else 0.0
    roi_status, roi_note = _roi_status(clinic, fee, measurable, holdout_n)
    roi = (net / fee) if (roi_status == ROI_OK and net is not None and fee > 0) else None

    return {
        "window_days": days,
        "contacted": treated_n,
        "recovered_count": treated_won,
        # Includes patients who would have returned anyway. Not causation.
        "gross_recovered": treated_amount,
        "treated_conversion": treated_rate,
        "holdout_size": holdout_n,
        "holdout_conversion": holdout_rate if measurable else None,
        "lift": lift,
        # The defensible number, or nothing at all.
        "net_attributable": net,
        "measurable": measurable,
        "measurable_note": (
            None if measurable else
            f"Cần ít nhất {MIN_HOLDOUT_FOR_MEASUREMENT} cơ hội trong nhóm đối chứng để "
            f"kết luận; hiện có {holdout_n}. Trước đó chỉ báo cáo doanh thu gộp."
        ),
        "subscription_cost": fee,
        "pricing_mode": clinic.pricing_mode if clinic else UNCONFIGURED,
        "pricing_label": PRICING_MODES.get(
            clinic.pricing_mode if clinic else UNCONFIGURED, UNCONFIGURED),
        "pilot_status": clinic.pilot_status if clinic else "none",
        "monthly_fee": float(clinic.monthly_fee or 0) if clinic else 0.0,
        "roi": roi,
        # Say which of the reasons it is. "ROI: —" with no explanation reads as
        # something broken, and a free pilot is not something broken.
        "roi_status": roi_status,
        "roi_note": roi_note,
    }


def _roi_status(clinic, fee: float, measurable: bool, holdout_n: int) -> tuple[str, Optional[str]]:
    """Why there is, or is not, an ROI figure.

    Commercial terms are read from ``pricing_mode`` and never inferred from the
    fee being zero. A zero can mean the clinic has not been priced yet, that
    they are on a free pilot, or that someone else is paying — three different
    statements, and dividing by any of them would invent a return.
    """
    mode = (clinic.pricing_mode if clinic else UNCONFIGURED) or UNCONFIGURED

    if mode == PILOT_FREE:
        return ROI_PILOT_FREE, "Pilot miễn phí — chưa tính ROI."
    if mode == SPONSORED:
        return ROI_SPONSORED, "Chi phí do bên khác tài trợ — ROI không áp dụng."
    if mode == UNCONFIGURED or fee <= 0:
        return ROI_NO_PRICE, (
            "Chưa cấu hình phí thuê bao, nên không có mẫu số để tính ROI. "
            "Đặt pricing_mode và monthly_fee khi phòng khám chuyển sang trả phí."
        )
    if not measurable:
        return ROI_NO_HOLDOUT, (
            f"Cần ít nhất {MIN_HOLDOUT_FOR_MEASUREMENT} cơ hội đối chứng để tách phần "
            f"doanh thu thực sự do CareDesk tạo ra; hiện có {holdout_n}."
        )
    return ROI_OK, None


def recovery_funnel(db: Session, clinic_id: int, days: int = 30) -> Dict[str, Any]:
    """Contacted -> responded -> booked -> completed, and the money at the end.

    Every step is counted from a record of something that happened: an action
    row for the contact, the patient's own message for the reply, an appointment
    for the booking, a revenue record for the money. No step is inferred from
    the one before it, which is why the drop between any two of them is worth
    reading.
    """
    since = clock.now() - timedelta(days=days)

    opportunities = db.query(RevenueOpportunity).filter(
        RevenueOpportunity.clinic_id == clinic_id,
        RevenueOpportunity.detected_at >= since,
        RevenueOpportunity.is_holdout == False,  # noqa: E712
        RevenueOpportunity.status != "superseded",
    ).all()
    ids = [o.id for o in opportunities]

    contacted = [o for o in opportunities if o.contacted_at is not None]
    responded = db.query(func.count(func.distinct(RevenueAction.opportunity_id))).filter(
        RevenueAction.opportunity_id.in_(ids or [0]),
        RevenueAction.status == "responded",
    ).scalar() or 0
    booked = [o for o in contacted if o.status in _CONVERTED]
    completed = [o for o in contacted if o.status == "recovered"]

    detected_value = sum(float(o.estimated_value or 0) for o in opportunities
                         if VALUE_KIND.get(o.opportunity_type) == NEW_REVENUE)

    return {
        "window_days": days,
        "detected": len(opportunities),
        "detected_value": detected_value,
        "contacted": len(contacted),
        "responded": int(responded),
        "booked": len(booked),
        "completed": len(completed),
        "revenue_recovered": sum(float(o.recovered_amount or 0) for o in completed),
    }


def attribution_summary(db: Session, clinic_id: int, days: int = 30) -> Dict[str, Any]:
    """Recovered money split by how defensible the credit is.

    Four buckets, and only the first two are the product's work:

    * **direct** — booked within days of being contacted.
    * **assisted** — booked later, still inside the attribution window. Real,
      but a weaker claim, so it is shown apart rather than folded in.
    * **organic** — never contacted and came back anyway. This is the clinic's
      own baseline; presenting it as recovered revenue would be the central lie
      this feature is built to avoid.
    * **unknown** — outside the window, or credited before attribution existed.
      Reported so the total reconciles, never counted as recovered.

    The holdout is reported separately again, because organic and holdout
    answer different questions: organic is "came back without a message",
    holdout is "was deliberately not sent one".
    """
    since = clock.now() - timedelta(days=days)
    rows = db.query(RevenueOpportunity).filter(
        RevenueOpportunity.clinic_id == clinic_id,
        RevenueOpportunity.detected_at >= since,
        RevenueOpportunity.status == "recovered",
    ).all()

    buckets = {
        key: {"class": key, "label": ATTRIBUTION_LABELS[key], "count": 0, "revenue": 0.0}
        for key in (DIRECT, ASSISTED, ORGANIC, UNKNOWN)
    }
    for opportunity in rows:
        key = opportunity.attribution_class or UNKNOWN
        bucket = buckets.setdefault(
            key, {"class": key, "label": ATTRIBUTION_LABELS.get(key, key),
                  "count": 0, "revenue": 0.0})
        bucket["count"] += 1
        bucket["revenue"] += float(opportunity.recovered_amount or 0)

    holdout = [o for o in rows if o.is_holdout]

    return {
        "window_days": days,
        "buckets": list(buckets.values()),
        # The only figure that may be described as revenue CareDesk recovered,
        # and even then only alongside the lift measurement.
        "attributable_revenue": buckets[DIRECT]["revenue"] + buckets[ASSISTED]["revenue"],
        "organic_revenue": buckets[ORGANIC]["revenue"],
        "holdout_revenue": sum(float(o.recovered_amount or 0) for o in holdout),
        "holdout_count": len(holdout),
        "direct_window_days": DIRECT_WINDOW_DAYS,
        "attribution_window_days": ATTRIBUTION_WINDOW_DAYS,
    }


def attribution_chain(db: Session, opportunity: RevenueOpportunity) -> Dict[str, Any]:
    """The whole trace for one opportunity, so a number can be argued with.

    Opportunity -> action -> booking -> appointment -> revenue record. An owner
    who does not believe a figure should be able to follow it to the visit and
    the receipt, otherwise "recovered revenue" is something they either take on
    faith or ignore.
    """
    actions = db.query(RevenueAction).filter(
        RevenueAction.opportunity_id == opportunity.id
    ).order_by(RevenueAction.id.asc()).all()

    appointment = db.get(Appointment, opportunity.resolved_appointment_id) \
        if opportunity.resolved_appointment_id else None
    record = db.get(RevenueRecord, opportunity.resolved_revenue_record_id) \
        if opportunity.resolved_revenue_record_id else None

    return {
        "opportunity_id": opportunity.id,
        "type": opportunity.opportunity_type,
        "status": opportunity.status,
        "attribution_class": opportunity.attribution_class,
        "is_holdout": opportunity.is_holdout,
        "detected_at": opportunity.detected_at,
        "actions": [{
            "id": a.id, "channel": a.channel, "template_code": a.template_code,
            "status": a.status, "sent_at": a.created_at, "responded_at": a.responded_at,
        } for a in actions],
        "booking_request_id": opportunity.resolved_booking_request_id,
        "appointment": {
            "id": appointment.id, "status": appointment.status,
            "start_time": appointment.start_time,
        } if appointment else None,
        "revenue_record": {
            "id": record.id, "amount": record.amount, "recorded_at": record.recorded_at,
        } if record else None,
        # Never the estimate. If no money was recorded this is None, and the
        # screen has to say so rather than showing what we hoped for.
        "revenue_recovered": opportunity.recovered_amount,
    }


def money_queue(db: Session, clinic_id: int, limit: int = 50,
                opportunity_type: Optional[str] = None) -> List[RevenueOpportunity]:
    """Open work, most valuable first. Holdout rows never appear.

    Hiding the holdout is not cosmetic — a receptionist who sees the row will
    ring them, and the experiment is gone.
    """
    query = db.query(RevenueOpportunity).filter(
        RevenueOpportunity.clinic_id == clinic_id,
        RevenueOpportunity.status.in_(("open", "contacted")),
        RevenueOpportunity.is_holdout == False,  # noqa: E712
    )
    if opportunity_type:
        query = query.filter(RevenueOpportunity.opportunity_type == opportunity_type)
    return sorted(query.all(), key=score, reverse=True)[:limit]

# --- helping the clinic fill in the one thing nothing can infer --------------

#: Typical repeat intervals, offered as a starting point on the setup screen and
#: **never written by the system**. A suggestion the clinic has to accept is a
#: prompt; a suggestion applied on their behalf is a guess wearing a default's
#: clothing, and it would be this engine deciding who gets chased.
#:
#: Keyed on words that appear in Vietnamese service names, matched on folded
#: text so "Botox" and "botox tiêm" both hit.
REVISIT_SUGGESTIONS = (
    (("botox", "tiem botox"), 90),
    (("filler", "tiem filler"), 180),
    (("mun", "acne", "tri mun"), 30),
    (("cham soc da", "facial", "soi da", "duong da"), 30),
    (("laser", "co2", "picosure", "yag"), 45),
    (("peel", "tay te bao", "thay da"), 30),
    (("triet long", "wax"), 45),
    (("meso", "hifu", "rf", "cang da"), 120),
    (("tam trang", "phun xam"), 90),
)


def suggest_revisit_days(service_name: str) -> Optional[int]:
    """A number to show next to the empty box, not one to put in it."""
    from backend.app.services.booking_flow import strip_accents

    folded = strip_accents(service_name or "")
    for keywords, days in REVISIT_SUGGESTIONS:
        if any(keyword in folded for keyword in keywords):
            return days
    return None


def recovery_readiness(db: Session, clinic_id: int) -> Dict[str, Any]:
    """Which detectors can actually see anything, and what is missing.

    Written because of how a pilot fails quietly: the clinic never sets a
    revisit interval, ``overdue_revisit`` returns nothing, and everyone
    concludes the engine cannot find much — when the truth is that the largest
    detector was switched off the whole time for want of one number.
    """
    clinic = db.get(Clinic, clinic_id)
    services = db.query(Service).filter(Service.clinic_id == clinic_id).all()
    configured = [s for s in services if s.revisit_interval_days]

    reviewed = bool(clinic and clinic.revisit_intervals_reviewed_at)
    return {
        "services_total": len(services),
        "services_with_interval": len(configured),
        "reviewed": reviewed,
        # Deliberately not "ready": a clinic whose treatments genuinely never
        # repeat is ready with zero intervals, as long as they have said so.
        "overdue_revisit_enabled": bool(configured),
        "needs_attention": not configured and not reviewed,
        "message": (
            None if configured or reviewed else
            "Chưa dịch vụ nào khai báo chu kỳ tái khám, nên nhóm 'Quá hạn tái khám' "
            "đang không tìm được ai. Hệ thống không tự đoán chu kỳ — phòng khám cần "
            "khai báo, hoặc xác nhận là không có dịch vụ nào lặp lại."
        ),
    }


def pilot_scorecard(db: Session, clinic_id: int, days: int = 30) -> Dict[str, Any]:
    """The five things a controlled pilot has to prove, each with its own number.

    Kept apart from the owner-facing dashboard on purpose. This answers "is the
    engine any good", which is a different question from "how much money came
    back", and the two have different denominators.
    """
    since = clock.now() - timedelta(days=days)
    rows = db.query(RevenueOpportunity).filter(
        RevenueOpportunity.clinic_id == clinic_id,
        RevenueOpportunity.detected_at >= since,
        RevenueOpportunity.status != "superseded",
    ).all()

    # 1. Does the engine find the right misses? Only staff can say, so this is
    #    the one figure the system cannot produce on its own.
    judged_yes = [o for o in rows if o.is_real_opportunity == "yes"]
    judged_no = [o for o in rows if o.is_real_opportunity == "no"]
    judged_total = len(judged_yes) + len(judged_no)
    precision = len(judged_yes) / judged_total if judged_total else None

    # 2. The money sample. Package opportunities are already paid for and cannot
    #    be "recovered", and a zero-valued opportunity has nothing to divide by,
    #    so both are outside the denominator rather than dragging it around.
    sample = [o for o in rows
              if VALUE_KIND.get(o.opportunity_type) == NEW_REVENUE
              and float(o.estimated_value or 0) > 0
              and not o.is_holdout]
    resolved = [o for o in sample if o.status in ("recovered", "lost")]
    recovered = [o for o in resolved if o.status == "recovered"]

    opportunity_value = sum(float(o.estimated_value or 0) for o in resolved)
    actual_recovered = sum(float(o.recovered_amount or 0) for o in recovered)

    return {
        "window_days": days,
        # --- is detection any good ---
        "detected": len(rows),
        "judged": judged_total,
        "judged_real": len(judged_yes),
        "judged_not_real": len(judged_no),
        "judged_unsure": len([o for o in rows if o.is_real_opportunity == "unsure"]),
        "detection_precision": precision,
        "precision_note": (
            None if judged_total else
            "Chưa có cơ hội nào được lễ tân đánh giá. Không có số này thì không "
            "phân biệt được 'tìm được nhiều' với 'tìm đúng'."
        ),
        # --- is the money real ---
        "sample_size": len(resolved),
        "opportunity_value": opportunity_value,
        "actual_recovered": actual_recovered,
        # Can legitimately exceed 100% when patients pay more than the estimate;
        # capping it would hide that the estimates are low.
        "recovery_rate": (actual_recovered / opportunity_value) if opportunity_value else None,
        # What one detected opportunity has actually been worth here. The number
        # that eventually decides what this product may be priced at.
        "revenue_per_opportunity": (actual_recovered / len(sample)) if sample else None,
        "sample_note": (
            "Mẫu chỉ gồm cơ hội sinh tiền mới, có giá trị > 0, ngoài nhóm đối chứng. "
            "Gói khách đã trả tiền nằm ngoài mẫu."
        ),
    }


def judge_opportunity(opportunity: RevenueOpportunity, verdict: str) -> RevenueOpportunity:
    """Record what staff thought of the detection itself."""
    opportunity.is_real_opportunity = verdict
    opportunity.judged_at = clock.now()
    return opportunity


#: The three answers to "was this really worth chasing?". Unsure is a real
#: answer and is kept out of the precision maths rather than forced to a side.
JUDGEMENTS = {
    "yes": "Có, đáng thu hồi",
    "no": "Không, không đáng",
    "unsure": "Không chắc",
}
