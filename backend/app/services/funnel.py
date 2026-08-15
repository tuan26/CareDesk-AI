"""Lead → Booking → Visit → Revenue, per channel.

The report a clinic owner actually buys the product for. Not "Facebook sent
1.000 clicks" — that is a number the ad platform already shows and nobody can
act on. This says how much money each channel produced, which is the only
version of the question that decides next month's budget.

Two rules make the numbers defensible:

**Everything is counted against first touch.** A patient found by an August
campaign and booked in September belongs to August's campaign. Splitting them by
the month the money arrived would credit whichever channel happened to be
running when they finally showed up.

**A patient is counted once.** Their revenue is theirs, not their channel's ×
however many visits. Otherwise a channel that brings a few loyal patients
outscores one that brings many new ones, purely by double counting.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from backend.app.models.models import (
    Appointment, BookingRequest, Conversation, PatientLead, RevenueRecord,
)
from backend.app.services.attribution import channel_of
from backend.app.core import clock


@dataclass
class ChannelRow:
    channel: str
    campaign: Optional[str] = None
    leads: int = 0
    bookings: int = 0     # patients who got as far as a booking or request
    visits: int = 0       # patients who actually turned up
    revenue: float = 0.0

    @property
    def booking_rate(self) -> float:
        return round(self.bookings / self.leads * 100, 1) if self.leads else 0.0

    @property
    def show_rate(self) -> float:
        """Of those who booked, how many came. A channel with a high booking
        rate and a low show rate is producing browsers, not patients."""
        return round(self.visits / self.bookings * 100, 1) if self.bookings else 0.0

    @property
    def revenue_per_lead(self) -> float:
        """The number to compare against cost per lead. Everything else on this
        row is a step towards it."""
        return round(self.revenue / self.leads, 0) if self.leads else 0.0


@dataclass
class Funnel:
    start_date: date
    end_date: date
    leads: int = 0
    bookings: int = 0
    visits: int = 0
    revenue: float = 0.0
    channels: List[ChannelRow] = field(default_factory=list)

    @property
    def lead_to_booking(self) -> float:
        return round(self.bookings / self.leads * 100, 1) if self.leads else 0.0

    @property
    def booking_to_visit(self) -> float:
        return round(self.visits / self.bookings * 100, 1) if self.bookings else 0.0


def _patient_window(db: Session, clinic_id: Optional[int],
                    start: datetime, end: datetime) -> List[PatientLead]:
    """Patients first seen in the window — the cohort the report is about."""
    query = db.query(PatientLead)
    if clinic_id:
        query = query.filter(PatientLead.clinic_id == clinic_id)
    # first_seen_at is only set for visitors carrying attribution, so created_at
    # is the fallback: a patient the receptionist typed in still counts as a
    # patient, they just belong to the "staff" channel.
    return [
        p for p in query.all()
        if start <= ((p.first_seen_at or p.created_at) or start).replace(tzinfo=None) <= end
    ]


def build(db: Session, clinic_id: Optional[int],
          start_date: Optional[date] = None,
          end_date: Optional[date] = None,
          by_campaign: bool = False) -> Funnel:
    end_date = end_date or clock.today()
    start_date = start_date or (end_date - timedelta(days=29))
    start = datetime.combine(start_date, datetime.min.time())
    end = datetime.combine(end_date, datetime.max.time())

    patients = _patient_window(db, clinic_id, start, end)
    funnel = Funnel(start_date=start_date, end_date=end_date)
    if not patients:
        return funnel

    ids = [p.id for p in patients]

    # A patient counts as "booked" if they reached either a real appointment or
    # a request awaiting staff. Requiring a confirmed appointment would blame
    # the channel for the clinic's own callback backlog.
    booked = {
        a.patient_id for a in db.query(Appointment).filter(
            Appointment.patient_id.in_(ids)).all()
    } | {
        r.patient_id for r in db.query(BookingRequest).filter(
            BookingRequest.patient_id.in_(ids)).all() if r.patient_id
    }
    visited = {
        a.patient_id for a in db.query(Appointment).filter(
            Appointment.patient_id.in_(ids),
            Appointment.status == "completed").all()
    }
    revenue: Dict[int, float] = {}
    for record in db.query(RevenueRecord).filter(RevenueRecord.patient_id.in_(ids)).all():
        revenue[record.patient_id] = revenue.get(record.patient_id, 0.0) + (record.amount or 0)

    rows: Dict[tuple, ChannelRow] = {}
    for patient in patients:
        key = (channel_of(patient), patient.utm_campaign if by_campaign else None)
        row = rows.setdefault(key, ChannelRow(channel=key[0], campaign=key[1]))
        row.leads += 1
        if patient.id in booked:
            row.bookings += 1
        if patient.id in visited:
            row.visits += 1
        row.revenue += revenue.get(patient.id, 0.0)

    funnel.channels = sorted(rows.values(), key=lambda r: r.revenue, reverse=True)
    funnel.leads = sum(r.leads for r in funnel.channels)
    funnel.bookings = sum(r.bookings for r in funnel.channels)
    funnel.visits = sum(r.visits for r in funnel.channels)
    funnel.revenue = sum(r.revenue for r in funnel.channels)
    return funnel


def confirmation_speed(db: Session, clinic_id: Optional[int],
                      start_date: Optional[date] = None,
                      end_date: Optional[date] = None) -> dict:
    """How fast the clinic answers a booking request, and what it costs them.

    This exists because "Facebook is underperforming" and "we take four hours to
    ring people back" look identical in a conversion rate and have completely
    different fixes. One is a budget decision; the other is a rota.
    """
    end_date = end_date or clock.today()
    start_date = start_date or (end_date - timedelta(days=29))
    start = datetime.combine(start_date, datetime.min.time())
    end = datetime.combine(end_date, datetime.max.time())

    query = db.query(Appointment).filter(
        Appointment.booking_requested_at >= start,
        Appointment.booking_requested_at <= end)
    if clinic_id:
        query = query.filter(Appointment.clinic_id == clinic_id)
    requested = query.all()
    if not requested:
        return {"requested": 0, "confirmed": 0, "confirm_rate_percent": 0.0,
                "median_minutes": None, "over_1h": 0}

    waits = []
    for appt in requested:
        if not appt.booking_confirmed_at:
            continue
        asked = appt.booking_requested_at.replace(tzinfo=None)
        answered = appt.booking_confirmed_at.replace(tzinfo=None)
        waits.append(max(0, (answered - asked).total_seconds() / 60))

    # Median, not mean: one request confirmed three days late would drag an
    # average far past anything a receptionist would recognise as their day.
    median = None
    if waits:
        ordered = sorted(waits)
        mid = len(ordered) // 2
        median = round(ordered[mid] if len(ordered) % 2 else
                       (ordered[mid - 1] + ordered[mid]) / 2)

    return {
        "requested": len(requested),
        "confirmed": len(waits),
        "confirm_rate_percent": round(len(waits) / len(requested) * 100, 1),
        "median_minutes": median,
        "over_1h": sum(1 for w in waits if w > 60),
    }


def ai_contribution(db: Session, clinic_id: Optional[int],
                    start_date: Optional[date] = None,
                    end_date: Optional[date] = None) -> dict:
    """What the AI itself did, which is a different question from the channel
    report: "which advert paid for this patient" versus "did the subscription
    earn its keep". Both get asked, usually in the same meeting."""
    end_date = end_date or clock.today()
    start_date = start_date or (end_date - timedelta(days=29))
    start = datetime.combine(start_date, datetime.min.time())
    end = datetime.combine(end_date, datetime.max.time())

    conv_q = db.query(Conversation).filter(
        Conversation.created_at >= start, Conversation.created_at <= end)
    appt_q = db.query(Appointment).filter(
        Appointment.created_at >= start, Appointment.created_at <= end)
    rev_q = db.query(RevenueRecord).filter(
        RevenueRecord.recorded_at >= start, RevenueRecord.recorded_at <= end)
    if clinic_id:
        conv_q = conv_q.filter(Conversation.clinic_id == clinic_id)
        appt_q = appt_q.filter(Appointment.clinic_id == clinic_id)
        rev_q = rev_q.filter(RevenueRecord.clinic_id == clinic_id)

    conversations = conv_q.all()
    appointments = appt_q.all()
    ai_booked = [a for a in appointments if (a.booking_source or "").startswith("ai_")]
    ai_revenue = sum(r.amount for r in rev_q.all() if (r.source or "").startswith("ai_"))

    # Leads captured = conversations that produced a contactable person. A chat
    # with no phone number is traffic, not a lead.
    leads = len({c.patient_id for c in conversations
                 if c.patient_id and c.patient and c.patient.phone})

    return {
        "conversations": len(conversations),
        "leads_captured": leads,
        "bookings_generated": len(ai_booked),
        "conversion_percent": round(len(ai_booked) / len(conversations) * 100, 1)
        if conversations else 0.0,
        "revenue": ai_revenue,
    }
