"""Which advert paid for this patient.

Two questions get confused constantly, and answering them with one field answers
neither:

    Where did this patient come from?   -> acquisition (this module)
    Who typed this booking in?          -> Appointment.booking_source

The first is what a clinic is spending money on. The second is what the product
does for them. A clinic asking "is Facebook worth it?" needs the first; a clinic
asking "is the AI earning its subscription?" needs the second. Reporting one as
the other makes both numbers untrustworthy.

**First touch, not last touch.** Last touch is easier to record and is the wrong
thing to report: the retargeting ad that catches someone on their way back takes
credit for a patient the original campaign found, so the channel that actually
works looks worse than the one that merely finished the job. The first visit
wins and is never overwritten.
"""
import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

#: Set on the first landing view, read when a lead is finally created — which
#: may be several pages and one chat conversation later.
COOKIE_NAME = "caredesk_attr"

#: Long enough to cover a normal consideration window for an aesthetics
#: treatment: people read, think, ask a friend, and come back a fortnight later.
COOKIE_MAX_AGE = 60 * 60 * 24 * 90

_FIELDS = ("utm_source", "utm_medium", "utm_campaign", "utm_content",
           "referrer", "landing_path")

#: Recognisable hosts, so an organic click from a search result is not filed as
#: "unknown" just because it carried no UTM parameters.
_HOST_CHANNELS = {
    "facebook": "facebook", "fb": "facebook", "instagram": "instagram",
    "google": "google", "bing": "google",
    "tiktok": "tiktok", "zalo": "zalo", "youtube": "youtube",
}


def from_request(request) -> Dict[str, Any]:
    """Attribution visible in this one request."""
    params = request.query_params
    data = {f: None for f in _FIELDS}

    for key in ("utm_source", "utm_medium", "utm_campaign", "utm_content"):
        value = params.get(key)
        if value:
            data[key] = value[:120]

    # Ad platforms send their own click ids and often no utm_source at all.
    if not data["utm_source"]:
        if params.get("fbclid"):
            data["utm_source"], data["utm_medium"] = "facebook", "paid"
        elif params.get("gclid"):
            data["utm_source"], data["utm_medium"] = "google", "paid"
        elif params.get("ttclid"):
            data["utm_source"], data["utm_medium"] = "tiktok", "paid"

    referrer = request.headers.get("referer") or ""
    if referrer:
        data["referrer"] = referrer[:300]
        if not data["utm_source"]:
            host = (urlparse(referrer).hostname or "").lower()
            for fragment, channel in _HOST_CHANNELS.items():
                if fragment in host:
                    data["utm_source"] = channel
                    data["utm_medium"] = data["utm_medium"] or "referral"
                    break

    data["landing_path"] = str(request.url.path)[:200]
    return data


def read_cookie(request) -> Dict[str, Any]:
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        return {}
    try:
        stored = json.loads(raw)
        return stored if isinstance(stored, dict) else {}
    except (ValueError, TypeError):
        # A corrupt cookie must not break a landing page for a real visitor.
        logger.warning("Cookie attribution hỏng, bỏ qua")
        return {}


def remember(request, response) -> Dict[str, Any]:
    """Store first touch, and leave it alone on every later visit.

    Returning the stored value rather than the current one is the point: a
    visitor arriving today from a retargeting ad still carries the campaign that
    found them the first time.
    """
    existing = read_cookie(request)
    if existing:
        return existing

    data = from_request(request)
    if not any(data.get(f) for f in ("utm_source", "utm_campaign", "referrer")):
        # Nothing worth remembering — a direct visit. Do not burn the cookie on
        # it, or a later click from an advert would find the slot already taken.
        return {}

    data["first_seen_at"] = datetime.now().isoformat()
    response.set_cookie(
        COOKIE_NAME, json.dumps(data, ensure_ascii=False),
        max_age=COOKIE_MAX_AGE, samesite="lax", httponly=False,
    )
    return data


def apply_to_lead(lead, data: Optional[Dict[str, Any]]) -> None:
    """Stamp a new patient record with where they came from.

    Only ever fills blanks. A returning patient keeps the campaign that first
    found them, because that is the campaign that earned the relationship.
    """
    if not data:
        return
    for field in _FIELDS:
        if data.get(field) and not getattr(lead, field, None):
            setattr(lead, field, str(data[field])[:300])

    if not lead.first_seen_at:
        raw = data.get("first_seen_at")
        try:
            lead.first_seen_at = datetime.fromisoformat(raw) if raw else datetime.now()
        except (ValueError, TypeError):
            lead.first_seen_at = datetime.now()


def channel_of(lead) -> str:
    """One label per patient for the channel report.

    Falls back down a ladder rather than to "unknown": a patient who arrived
    through the Zalo widget is a Zalo patient whether or not anyone tagged the
    link, and calling that "unknown" hides a working channel.
    """
    if getattr(lead, "utm_source", None):
        return lead.utm_source.lower()

    referrer = getattr(lead, "referrer", None)
    if referrer:
        host = (urlparse(referrer).hostname or "").lower()
        for fragment, channel in _HOST_CHANNELS.items():
            if fragment in host:
                return channel
        return "referral"

    source = (getattr(lead, "source", None) or "").lower()
    if source in ("zalo", "facebook"):
        return source
    if source == "staff":
        return "staff"
    if source in ("web", "web_form"):
        # Reached the site with no campaign and no referrer: typed the address,
        # scanned a printed QR code, or came from a messaging app that strips
        # referrers. Genuinely direct, not missing data.
        return "direct"
    return source or "direct"
