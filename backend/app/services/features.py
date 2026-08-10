"""Feature flags.

Built before turning anything off, on purpose. The alternative — deleting code
or commenting out routes — means paying for the same feature twice: once to
build it, once to rebuild it when the market asks for it back. Everything here
stays in the codebase, keeps its tests, and is simply not reachable.

Resolution order, most specific first:

    1. a row for this clinic          (clinic decided)
    2. a row with clinic_id = NULL    (vendor default, editable at runtime)
    3. DEFAULTS below                 (what ships)
"""
import logging
from typing import Dict, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.app.models.models import FeatureFlag

logger = logging.getLogger(__name__)

# Flags that gate a whole area of the product.
CHAIN_CONSOLE = "chain_console"
MULTILANG = "multilang"
COPILOT = "copilot"
FACEBOOK_CAPI = "facebook_capi"

#: Shipped state. All four are off for the first release: the product being sold
#: is "more bookings, fewer no-shows" for a single da liễu/thẩm mỹ clinic, and
#: every one of these widens that promise without strengthening it.
DEFAULTS: Dict[str, bool] = {
    # Chain/multi-clinic console. The Organization -> Clinic -> Branch hierarchy
    # stays in the schema (it is what makes branches work at all); only the
    # console and the chain pricing tier are hidden.
    CHAIN_CONSOLE: False,
    # EN/JA landing + chat. Turn on per clinic only once they have actually
    # translated their service descriptions — otherwise the English page renders
    # English chrome around Vietnamese content and looks broken.
    MULTILANG: False,
    # Staff-facing AI assistant in the dashboard. Off the two core flows, costs
    # tokens, and widens the support surface.
    COPILOT: False,
    # Meta Conversions API. Only meaningful for a clinic running paid ads.
    FACEBOOK_CAPI: False,
}

#: Human labels for the settings screen.
LABELS = {
    CHAIN_CONSOLE: "Console chuỗi phòng khám (/org)",
    MULTILANG: "Trang & chat đa ngôn ngữ (EN/JA)",
    COPILOT: "Trợ lý AI cho nhân viên trong Dashboard",
    FACEBOOK_CAPI: "Gửi sự kiện về Facebook Ads (CAPI)",
}


def is_enabled(db: Session, clinic_id: Optional[int], key: str) -> bool:
    if key not in DEFAULTS:
        logger.warning("Hỏi một cờ tính năng không tồn tại: %s", key)
        return False

    # `IN (1, NULL)` never matches the NULL row — SQL NULL is not equal to
    # anything, including itself — so the vendor-wide default has to be fetched
    # with an explicit IS NULL.
    scope = FeatureFlag.clinic_id.is_(None)
    if clinic_id:
        scope = or_(FeatureFlag.clinic_id == clinic_id, scope)

    rows = db.query(FeatureFlag).filter(FeatureFlag.key == key, scope).all()

    for row in rows:                       # clinic-specific wins
        if clinic_id and row.clinic_id == clinic_id:
            return row.enabled
    for row in rows:                       # then the vendor-wide default
        if row.clinic_id is None:
            return row.enabled
    return DEFAULTS[key]


def all_flags(db: Session, clinic_id: Optional[int]) -> Dict[str, bool]:
    return {key: is_enabled(db, clinic_id, key) for key in DEFAULTS}


def set_flag(db: Session, clinic_id: Optional[int], key: str, enabled: bool) -> None:
    """Upsert one flag. clinic_id=None sets the vendor-wide default."""
    if key not in DEFAULTS:
        raise ValueError(f"Cờ tính năng không hợp lệ: {key}")

    row = db.query(FeatureFlag).filter(
        FeatureFlag.key == key,
        FeatureFlag.clinic_id == clinic_id,
    ).first()
    if row:
        row.enabled = enabled
    else:
        db.add(FeatureFlag(clinic_id=clinic_id, key=key, enabled=enabled))
    db.commit()
