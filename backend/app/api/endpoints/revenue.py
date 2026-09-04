"""Revenue Recovery: the leakage dashboard, the money queue, and closing the loop.

The loop this serves is Detect -> Act -> Recover -> Prove. Detection lives in
services/revenue_recovery.py; this module is where staff see the result and
record what they did about it, which is the only way the "prove" half ever gets
any data.

One rule runs through every response here: a number that cannot be defended is
not returned. ``recoverable_expected`` is separated from ``recoverable_gross``,
already-collected package money is kept out of both, and ROI is None until the
holdout is large enough to support it.
"""
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.api.deps import verify_owner, verify_receptionist_or_above
from backend.app.core import clock
from backend.app.core.database import get_db
from backend.app.models.models import (
    Clinic, PatientLead, RevenueAction, RevenueOpportunity, Service, User,
)
from backend.app.services import revenue_recovery as rr
from backend.app.services.audit import log_action

router = APIRouter()


def _clinic_id(user: User) -> int:
    if not user.clinic_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Tài khoản chưa gắn với phòng khám nào.")
    return user.clinic_id


def _serialize(db: Session, opportunity: RevenueOpportunity) -> dict:
    patient = db.get(PatientLead, opportunity.patient_id)
    service = db.get(Service, opportunity.service_id) if opportunity.service_id else None
    return {
        "id": opportunity.id,
        "type": opportunity.opportunity_type,
        "type_label": rr.TYPE_LABELS.get(opportunity.opportunity_type, opportunity.opportunity_type),
        "value_kind": rr.VALUE_KIND.get(opportunity.opportunity_type, rr.NEW_REVENUE),
        "patient": {
            "id": patient.id if patient else None,
            "name": patient.full_name if patient else "—",
            "phone": patient.phone if patient else None,
        },
        "service_name": service.name if service else None,
        "estimated_value": opportunity.estimated_value,
        "probability": opportunity.probability,
        "expected_value": (opportunity.estimated_value or 0) * (opportunity.probability or 0),
        "urgency_days": opportunity.urgency_days,
        "score": rr.score(opportunity),
        # The "why" behind the number. Without this the queue is an oracle and
        # staff stop trusting it the first time one entry looks wrong.
        "reasons": opportunity.reasons or [],
        "recommended_channel": opportunity.recommended_channel,
        "recommended_message": opportunity.recommended_message,
        "status": opportunity.status,
        "detected_at": opportunity.detected_at,
        "contacted_at": opportunity.contacted_at,
    }


# --- the dashboard -----------------------------------------------------------

@router.get("/leakage")
def revenue_leakage(
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above),
) -> Any:
    """Where money is leaking, by bucket, with the caveats attached."""
    clinic_id = _clinic_id(current_user)
    summary = rr.leakage_summary(db, clinic_id)
    summary["holdout_note"] = (
        f"{int(rr.HOLDOUT_RATE * 100)}% cơ hội được giữ lại làm nhóm đối chứng và "
        f"không liên hệ, để đo phần doanh thu thực sự do CareDesk mang lại. "
        f"Các con số trên không bao gồm nhóm này."
    )
    return summary


@router.get("/performance")
def performance(
    days: int = Query(90, ge=7, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above),
) -> Any:
    """Recovered revenue, and how much of it CareDesk may take credit for."""
    return rr.recovery_performance(db, _clinic_id(current_user), days=days)


# --- the queue ---------------------------------------------------------------

@router.get("/queue")
def money_queue(
    limit: int = Query(50, ge=1, le=200),
    type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above),
) -> Any:
    """Today's work, highest expected value first."""
    if type and type not in rr.ALL_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Nhóm cơ hội không hợp lệ: {type}")
    clinic_id = _clinic_id(current_user)
    rows = rr.money_queue(db, clinic_id, limit=limit, opportunity_type=type)
    return {
        "items": [_serialize(db, o) for o in rows],
        "total_expected": sum((o.estimated_value or 0) * (o.probability or 0) for o in rows),
    }


@router.post("/detect")
def run_detection(
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above),
) -> Any:
    """Re-scan now instead of waiting for the nightly run."""
    clinic_id = _clinic_id(current_user)
    result = rr.run_detection(db, clinic_id)
    log_action(db, current_user.id, "revenue_detection_run", details=str(result))
    return {"detected": result}


# --- closing the loop --------------------------------------------------------

class ContactPayload(BaseModel):
    channel: Optional[str] = Field(None, description="zalo | sms | call")
    #: The ZNS/SMS template it went out on, so a complaint can be traced back
    #: and so the clinic can see which wording actually recovers people.
    template_code: Optional[str] = None
    #: What was really sent, if staff edited the draft. Stored as sent, not as
    #: drafted — otherwise the log records our suggestion instead of their work.
    message: Optional[str] = None
    note: Optional[str] = None


@router.post("/opportunities/{opportunity_id}/contacted")
def mark_contacted(
    opportunity_id: int,
    payload: ContactPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above),
) -> Any:
    """Staff reached out. Records the act, not a send.

    Nothing is dispatched from here on purpose: the first version of an outbound
    engine that sends by itself is the version that gets a clinic's Zalo OA
    suspended for marketing on a transactional template. The message is drafted,
    a human sends it, and this endpoint records that they did.
    """
    opportunity = _owned(db, opportunity_id, current_user)
    if opportunity.is_holdout:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cơ hội này thuộc nhóm đối chứng — liên hệ sẽ làm hỏng phép đo doanh thu thu hồi.",
        )
    channel = payload.channel or opportunity.recommended_channel or "call"
    rr.record_action(db, opportunity, channel=channel, message=payload.message,
                     template_code=payload.template_code, user_id=current_user.id)
    opportunity.recommended_channel = channel
    db.commit()
    log_action(db, current_user.id, "revenue_opportunity_contacted", details=str(opportunity_id))
    return _serialize(db, opportunity)


@router.post("/actions/{action_id}/responded")
def mark_responded(
    action_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above),
) -> Any:
    """The patient answered.

    Replies on a connected channel are picked up automatically from the
    patient's own messages; this is for a phone call, which leaves no trace the
    system can read.
    """
    action = db.get(RevenueAction, action_id)
    if not action or action.clinic_id != _clinic_id(current_user):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy lượt liên hệ.")
    action.status = "responded"
    action.responded_at = clock.now()
    db.commit()
    return {"id": action.id, "status": action.status, "responded_at": action.responded_at}


class OutcomePayload(BaseModel):
    outcome: str = Field(..., description="recovered | lost | dismissed")
    loss_reason: Optional[str] = None
    recovered_amount: Optional[float] = None
    #: Asked at the same moment, because this is when staff have the case in
    #: front of them and know whether it was ever worth chasing.
    verdict: Optional[str] = Field(None, description="yes | no | unsure")


@router.post("/opportunities/{opportunity_id}/outcome")
def record_outcome(
    opportunity_id: int,
    payload: OutcomePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above),
) -> Any:
    """What happened. This is the data every rate on the dashboard learns from.

    "lost" requires a reason from the closed list — free text cannot be counted,
    and knowing that eleven of last month's losses were "chê giá" is the whole
    reason for asking.
    """
    opportunity = _owned(db, opportunity_id, current_user)
    if payload.outcome not in ("recovered", "lost", "dismissed"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Kết quả phải là recovered, lost hoặc dismissed.")
    if payload.outcome == "lost":
        if payload.loss_reason not in rr.LOSS_REASONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Lý do mất phải thuộc: {', '.join(rr.LOSS_REASONS)}",
            )
        opportunity.loss_reason = payload.loss_reason

    if payload.verdict:
        if payload.verdict not in rr.JUDGEMENTS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail=f"Đánh giá phải là: {', '.join(rr.JUDGEMENTS)}")
        rr.judge_opportunity(opportunity, payload.verdict)

    opportunity.status = payload.outcome
    opportunity.resolved_at = clock.now()
    if payload.outcome == "recovered":
        opportunity.recovered_amount = (
            payload.recovered_amount
            if payload.recovered_amount is not None
            else float(opportunity.estimated_value or 0)
        )
    db.commit()
    log_action(db, current_user.id, f"revenue_opportunity_{payload.outcome}", details=str(opportunity_id))
    return _serialize(db, opportunity)


@router.get("/funnel")
def funnel(
    days: int = Query(30, ge=7, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above),
) -> Any:
    """Contacted -> responded -> booked -> completed, and the money at the end.

    Each step is counted from its own record rather than inferred from the step
    before, so the drop between any two of them is real and worth reading.
    """
    return rr.recovery_funnel(db, _clinic_id(current_user), days=days)


@router.get("/attribution")
def attribution(
    days: int = Query(30, ge=7, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above),
) -> Any:
    """Recovered money split by how defensible the credit is.

    Only ``attributable_revenue`` (direct + assisted) may be described as
    revenue CareDesk recovered. Organic is the clinic's own baseline and is
    reported so the total reconciles, never so it can be added in.
    """
    return rr.attribution_summary(db, _clinic_id(current_user), days=days)


@router.get("/opportunities/{opportunity_id}/chain")
def chain(
    opportunity_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above),
) -> Any:
    """Follow one figure all the way to the visit and the receipt.

    An owner who does not believe a number has to be able to argue with it;
    without this the dashboard is something they take on faith or ignore.
    """
    return rr.attribution_chain(db, _owned(db, opportunity_id, current_user))


@router.get("/loss-reasons")
def loss_reasons(current_user: User = Depends(verify_receptionist_or_above)) -> Any:
    """The closed list behind the "Vì sao mất?" question."""
    return [{"code": code, "label": label} for code, label in rr.LOSS_REASONS.items()]


@router.get("/loss-analysis")
def loss_analysis(
    days: int = Query(90, ge=7, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above),
) -> Any:
    """Why the clinic is losing people, ranked by the money behind each reason.

    Counting reasons alone hides the important case: two losses to "chê giá" on
    a ₫20 triệu package matter more than nine on a ₫300k consult.
    """
    from datetime import timedelta

    from sqlalchemy import func

    since = clock.now() - timedelta(days=days)
    rows = db.query(
        RevenueOpportunity.loss_reason,
        func.count(RevenueOpportunity.id),
        func.sum(RevenueOpportunity.estimated_value),
    ).filter(
        RevenueOpportunity.clinic_id == _clinic_id(current_user),
        RevenueOpportunity.status == "lost",
        RevenueOpportunity.loss_reason != None,  # noqa: E711
        RevenueOpportunity.resolved_at >= since,
    ).group_by(RevenueOpportunity.loss_reason).all()

    result = [{
        "code": code,
        "label": rr.LOSS_REASONS.get(code, code),
        "count": int(count or 0),
        "value_lost": float(value or 0),
    } for code, count, value in rows]
    result.sort(key=lambda r: r["value_lost"], reverse=True)
    return {"window_days": days, "reasons": result}


# --- per-service revisit interval -------------------------------------------

class RevisitIntervalPayload(BaseModel):
    revisit_interval_days: Optional[int] = Field(
        None, ge=1, le=1095,
        description="NULL = dịch vụ làm một lần, không nhắc tái khám.",
    )


@router.put("/services/{service_id}/revisit-interval")
def set_revisit_interval(
    service_id: int,
    payload: RevisitIntervalPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_owner),
) -> Any:
    """The clinic states which treatments repeat, and how often.

    Owner-only, and nothing guesses it. This single number decides who gets
    chased for a revisit; a wrong one turns the product into a nuisance for
    exactly the patients the clinic most wants to keep.
    """
    service = db.get(Service, service_id)
    if not service or service.clinic_id != _clinic_id(current_user):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy dịch vụ.")
    service.revisit_interval_days = payload.revisit_interval_days
    db.commit()
    log_action(db, current_user.id, "service_revisit_interval_set",
               details=f"{service_id}={payload.revisit_interval_days}")
    return {"id": service.id, "name": service.name,
            "revisit_interval_days": service.revisit_interval_days}


@router.get("/services/revisit-intervals")
def list_revisit_intervals(
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above),
) -> Any:
    """Which services have an interval set — i.e. what recall can even see.

    ``suggested_days`` is shown beside the empty box and is never written by
    anything but a person clicking it. A suggestion the clinic accepts is a
    prompt; one applied on their behalf is a guess wearing a default's clothes,
    and it would be the engine deciding who gets chased.
    """
    services = db.query(Service).filter(
        Service.clinic_id == _clinic_id(current_user)
    ).order_by(Service.name.asc()).all()
    return [{
        "id": s.id, "name": s.name, "price": s.price,
        "revisit_interval_days": s.revisit_interval_days,
        "suggested_days": rr.suggest_revisit_days(s.name),
    } for s in services]


@router.post("/services/revisit-intervals/reviewed")
def mark_intervals_reviewed(
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_owner),
) -> Any:
    """The clinic has been through the screen and is done.

    Needed because "no interval is set" and "nothing here repeats" look
    identical in the data, and a clinic in the second case would otherwise be
    nagged forever — or invent a number to make the warning go away, which is
    the one input this engine must never be given.
    """
    clinic = db.get(Clinic, _clinic_id(current_user))
    clinic.revisit_intervals_reviewed_at = clock.now()
    db.commit()
    log_action(db, current_user.id, "revisit_intervals_reviewed",
               details=str(clinic.revisit_intervals_reviewed_at))
    return rr.recovery_readiness(db, clinic.id)


@router.get("/readiness")
def readiness(
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above),
) -> Any:
    """Which detectors can actually see anything, and what is missing.

    A pilot fails quietly like this: nobody sets a revisit interval, the largest
    detector returns nothing, and everyone concludes the engine cannot find much.
    """
    return rr.recovery_readiness(db, _clinic_id(current_user))


@router.get("/pilot")
def pilot(
    days: int = Query(30, ge=7, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above),
) -> Any:
    """The pilot scorecard: is the engine any good, and is the money real.

    Separate from the owner dashboard because the two answer different
    questions and use different denominators. Detection precision comes from
    staff verdicts and cannot be computed — no judgements, no number.
    """
    return rr.pilot_scorecard(db, _clinic_id(current_user), days=days)


class JudgementPayload(BaseModel):
    verdict: str = Field(..., description="yes | no | unsure")


@router.post("/opportunities/{opportunity_id}/judge")
def judge(
    opportunity_id: int,
    payload: JudgementPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above),
) -> Any:
    """"Was this really worth chasing?" — the only measure of detection quality.

    Conversion cannot answer it. An opportunity can be perfectly real and still
    not convert, and a bad one that happens to convert says nothing good about
    the detector. Judgeable whatever the outcome, including on the holdout,
    because whether a miss was real has nothing to do with contacting anyone.
    """
    if payload.verdict not in rr.JUDGEMENTS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Đánh giá phải là: {', '.join(rr.JUDGEMENTS)}")
    opportunity = _owned(db, opportunity_id, current_user)
    rr.judge_opportunity(opportunity, payload.verdict)
    db.commit()
    return {"id": opportunity.id, "is_real_opportunity": opportunity.is_real_opportunity,
            "judged_at": opportunity.judged_at}


@router.get("/judgements")
def judgements(current_user: User = Depends(verify_receptionist_or_above)) -> Any:
    return [{"code": code, "label": label} for code, label in rr.JUDGEMENTS.items()]


def _owned(db: Session, opportunity_id: int, user: User) -> RevenueOpportunity:
    opportunity = db.get(RevenueOpportunity, opportunity_id)
    if not opportunity or opportunity.clinic_id != _clinic_id(user):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy cơ hội.")
    return opportunity
