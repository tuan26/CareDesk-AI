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


# --- do not contact ----------------------------------------------------------

#: What a patient says when they want the messages to stop. Folded before
#: matching, because almost nobody types diacritics on a phone.
#:
#: Kept deliberately tight. A false positive here silently cuts a real customer
#: off from the clinic, so "khong" alone is not on the list — plenty of ordinary
#: replies contain it ("khong biet", "khong ranh hom nay").
_OPT_OUT_PHRASES = (
    "dung nhan nua", "dung nhan tin nua", "dung gui nua", "dung lien he",
    "khong nhan tin nua", "khong muon nhan", "ngung nhan tin", "ngung gui",
    "huy nhan tin", "bo theo doi", "spam", "unsubscribe",
    # "ko" for "không" is not slang here, it is how people type on a phone.
    # Leaving it out meant "ko muon nhan tin" read as an ordinary reply.
    "ko muon nhan", "ko nhan tin nua", "ko gui nua", "ko lien he", "ko nhan nua",
)

#: Whole-message refusals. "huy" is deliberately absent: Huy is one of the most
#: common Vietnamese given names, and "hủy" on its own almost always means
#: cancel my appointment. Either reading would silently cut a real customer off
#: from the clinic for ever, which is far worse than missing one opt-out.
_OPT_OUT_EXACT = ("stop", "unsubscribe", "huy nhan tin", "dung nhan")

OPT_OUT_ACK = (
    "Dạ em đã ghi nhận, bên em sẽ không gửi tin nhắn giới thiệu cho mình nữa ạ. "
    "Nếu mình có lịch hẹn thì em vẫn nhắc giờ khám thôi. Cảm ơn mình đã phản hồi!"
)


def detects_opt_out(text: str) -> bool:
    """Did the patient just ask to be left alone?"""
    from backend.app.services.booking_flow import strip_accents

    folded = strip_accents(text or "").strip()
    if not folded:
        return False
    # "stop" inside a sentence is usually English sprinkled into a normal
    # message, so it only counts as the entire reply.
    if folded in _OPT_OUT_EXACT:
        return True
    return any(phrase in folded for phrase in _OPT_OUT_PHRASES)


def opt_out(db: Session, patient: PatientLead, reason: str = "patient_request") -> PatientLead:
    patient.contact_opt_out = True
    patient.opt_out_at = clock.now()
    patient.opt_out_reason = reason
    return patient


def opt_in(db: Session, patient: PatientLead) -> PatientLead:
    """Only ever from an explicit request — never as a side effect of the
    patient simply messaging again. Someone asking a question has not withdrawn
    their refusal to be marketed at."""
    patient.contact_opt_out = False
    patient.opt_out_at = None
    patient.opt_out_reason = None
    return patient


def may_send_marketing(patient: Optional[PatientLead]) -> bool:
    """The gate every proactive message passes through.

    Marketing only. An appointment reminder for a visit the patient booked
    themselves is not marketing, and withholding it would be the opposite of
    respecting what they asked for — they said stop selling to me, not stop
    telling me when to turn up.
    """
    if patient is None:
        return False
    return not bool(patient.contact_opt_out)
