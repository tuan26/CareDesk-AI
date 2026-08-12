"""Do patients come back?

The number this replaces was a running total of everyone who had ever visited
twice. It only ever went up, so a three-year-old clinic showed a large figure
whether CareDesk helped or not — it could never demonstrate a change, which is
the only thing a retention metric is for.

What is measured here instead is a **cohort rate**: of the patients who came for
the first time during one window, what share came back within the follow-up
period. That can move, and moving is the point.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from backend.app.models.models import Appointment

#: How long a patient gets to come back before the cohort is judged. Chosen to
#: match the 30-day recall automation plus room for the appointment itself to be
#: scheduled and attended.
DEFAULT_RETURN_WINDOW_DAYS = 90

#: How wide a slice of first-time patients forms one cohort.
DEFAULT_COHORT_DAYS = 90

#: Below this, the percentage is noise — one patient moves it by double digits.
MIN_COHORT_FOR_CONFIDENCE = 10


@dataclass
class ReturnRate:
    percent: Optional[float]      # None when the cohort is empty
    cohort_size: int
    returned: int
    window_days: int
    cohort_start: datetime
    cohort_end: datetime

    @property
    def is_reliable(self) -> bool:
        return self.cohort_size >= MIN_COHORT_FOR_CONFIDENCE


def return_rate(db: Session, clinic_id: Optional[int],
                window_days: int = DEFAULT_RETURN_WINDOW_DAYS,
                cohort_days: int = DEFAULT_COHORT_DAYS,
                now: Optional[datetime] = None) -> ReturnRate:
    """Share of first-time patients who came back within `window_days`.

    Only **mature** cohorts count. A patient whose first visit was last Tuesday
    has not had ninety days to return, so including them would drag the rate
    toward zero and make the metric look worse the more new patients arrive —
    exactly backwards. The cohort therefore ends `window_days` ago.

    Counts completed visits only. A booking that was never attended says nothing
    about whether the patient came back.
    """
    now = now or datetime.now()
    cohort_end = now - timedelta(days=window_days)
    cohort_start = cohort_end - timedelta(days=cohort_days)

    query = db.query(Appointment).filter(Appointment.status == "completed")
    if clinic_id:
        query = query.filter(Appointment.clinic_id == clinic_id)

    # First completed visit per patient, across all of history: someone who has
    # been coming for years is not a first-time patient just because this window
    # happens to be their earliest visit inside it.
    first_visit: dict[int, datetime] = {}
    visits: dict[int, list] = {}
    for appt in query.all():
        if appt.patient_id is None:
            continue
        start = appt.start_time.replace(tzinfo=None)
        visits.setdefault(appt.patient_id, []).append(start)
        if appt.patient_id not in first_visit or start < first_visit[appt.patient_id]:
            first_visit[appt.patient_id] = start

    cohort = [pid for pid, first in first_visit.items()
              if cohort_start <= first <= cohort_end]

    returned = 0
    for pid in cohort:
        first = first_visit[pid]
        deadline = first + timedelta(days=window_days)
        if any(first < v <= deadline for v in visits[pid]):
            returned += 1

    percent = round(returned / len(cohort) * 100, 1) if cohort else None
    return ReturnRate(
        percent=percent, cohort_size=len(cohort), returned=returned,
        window_days=window_days, cohort_start=cohort_start, cohort_end=cohort_end,
    )
