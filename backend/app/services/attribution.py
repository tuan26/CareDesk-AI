"""Which advert paid for this patient.

Two questions get confused constantly, and answering them with one field answers
neither:

    Where did this patient come from?   -> acquisition (this module)
    Who typed this booking in?          -> Appointment.booking_source

The first is what a clinic is spending money on. The second is what the product
does for them. A clinic asking "is Facebook worth it?" needs the first; a clinic
asking "is the AI earning its subscription?" needs the second. Reporting one as
the other makes both numbers untrustworthy.

**First touch owns the credit; latest touch is kept anyway.** Last touch is the
wrong thing to report — the retargeting ad that catches someone on their way back
would take credit for a patient the original campaign found, making the channel
that actually works look worse than the one that merely finished the job. So
acquisition is always first touch, written once and never moved. The latest touch
is recorded separately because it answers a different, useful question: what
brought this patient back on the day they finally booked. Two facts, two fields,
no argument about which one a report means.
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
           "utm_term", "click_id", "referrer", "landing_path")

#: Mirrored onto the lead as latest_* — a deliberately smaller set. Latest touch
#: exists to answer "what brought them back", not to reconstruct a second full
#: acquisition record.
_LATEST_FIELDS = ("utm_source", "utm_medium", "utm_campaign", "landing_path")

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

    for key in ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"):
        value = params.get(key)
        if value:
            data[key] = value[:120]

    # Ad platforms send their own click ids and often no utm_source at all.
    for param, platform in (("fbclid", "facebook"), ("gclid", "google"),
                            ("ttclid", "tiktok")):
        click = params.get(param)
        if click:
            data["click_id"] = click[:120]
            if not data["utm_source"]:
                data["utm_source"], data["utm_medium"] = platform, "paid"
            break

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


def _normalise(stored: Dict[str, Any]) -> Dict[str, Any]:
    """Accept the current {first, latest, touches} shape and the flat one that
    cookies written before latest-touch existed still carry."""
    if "first" in stored:
        return stored
    return {"first": stored, "latest": dict(stored), "touches": 1} if stored else {}


def remember(request, response) -> Dict[str, Any]:
    """Record this visit: first touch once, latest touch every time.

    The two exist for different questions and must not be merged. First touch is
    acquisition credit and is written once — a visitor arriving today from a
    retargeting ad still belongs to the campaign that originally found them.
    Latest touch is overwritten freely, and answers what brought them back on the
    day they finally converted.
    """
    stored = _normalise(read_cookie(request))
    current = from_request(request)
    identifiable = any(current.get(f) for f in ("utm_source", "utm_campaign", "referrer"))
    now = datetime.now().isoformat()

    if not stored:
        if not identifiable:
            # A plain visit must not claim the first-touch slot, or an advert
            # clicked an hour later would find it already taken.
            return {}
        current["first_seen_at"] = now
        stored = {"first": current, "latest": dict(current), "touches": 1}
    else:
        stored["touches"] = int(stored.get("touches") or 1) + 1
        if identifiable:
            stored["latest"] = current
        else:
            # Keep the previous campaign labels but move the timestamp: a direct
            # return visit is still a visit, it just did not come from anywhere
            # new.
            stored.setdefault("latest", dict(stored["first"]))
            stored["latest"]["landing_path"] = current.get("landing_path")
    stored["latest_touch_at"] = now

    response.set_cookie(
        COOKIE_NAME, json.dumps(stored, ensure_ascii=False),
        max_age=COOKIE_MAX_AGE, samesite="lax", httponly=False,
    )
    return stored


def apply_to_lead(lead, data: Optional[Dict[str, Any]]) -> None:
    """Stamp a patient record with where they came from, and where they last
    came back from.

    First-touch fields are filled only when blank, which makes them effectively
    immutable once a patient exists: the campaign that earned the relationship
    keeps it, no matter how many adverts they click afterwards.
    """
    stored = _normalise(data or {})
    if not stored:
        return

    first = stored.get("first") or {}
    for field in _FIELDS:
        if first.get(field) and not getattr(lead, field, None):
            setattr(lead, field, str(first[field])[:300])

    if not lead.first_seen_at:
        lead.first_seen_at = _parse(first.get("first_seen_at"))

    latest = stored.get("latest") or first
    for field in _LATEST_FIELDS:
        if latest.get(field):
            setattr(lead, f"latest_{field}", str(latest[field])[:300])
    lead.latest_touch_at = _parse(stored.get("latest_touch_at"))
    lead.touch_count = max(int(stored.get("touches") or 1), lead.touch_count or 1)


def _parse(raw: Optional[str]) -> datetime:
    try:
        return datetime.fromisoformat(raw) if raw else datetime.now()
    except (ValueError, TypeError):
        return datetime.now()


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
