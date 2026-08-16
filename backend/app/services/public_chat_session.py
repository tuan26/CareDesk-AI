"""Short-lived, conversation-bound credentials for unauthenticated web chat."""
import base64
import hashlib
import hmac
import time
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from sqlalchemy.orm import Session
from backend.app.core.config import settings
from backend.app.models.models import PublicChatSession

_TOKEN_VERSION = "v1"


def create_public_chat_token(conversation_id: int, ttl_seconds: Optional[int] = None) -> str:
    """Create an opaque signed token; no secret is persisted in the database."""
    expires_at = int(time.time()) + (ttl_seconds or settings.PUBLIC_CHAT_SESSION_TTL_SECONDS)
    payload = f"{_TOKEN_VERSION}.{conversation_id}.{expires_at}"
    signature = hmac.new(settings.SECRET_KEY.encode(), payload.encode(), hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    return f"{payload}.{encoded_signature}"


def verify_public_chat_token(conversation_id: int, token: Optional[str]) -> bool:
    """Legacy stateless verifier, retained while old widgets migrate."""
    if not token:
        return False
    try:
        version, token_conversation_id, expires_at, signature = token.split(".", 3)
        if version != _TOKEN_VERSION or int(token_conversation_id) != conversation_id:
            return False
        if int(expires_at) < int(time.time()):
            return False
        payload = f"{version}.{token_conversation_id}.{expires_at}"
        expected = hmac.new(settings.SECRET_KEY.encode(), payload.encode(), hashlib.sha256).digest()
        supplied = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
        return hmac.compare_digest(expected, supplied)
    except (TypeError, ValueError, UnicodeEncodeError):
        return False


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def issue_public_chat_session(db: Session, conversation_id: int) -> str:
    """Issue an opaque, database-revocable token for a single conversation."""
    raw_token = secrets.token_urlsafe(32)
    db.add(PublicChatSession(
        conversation_id=conversation_id,
        token_hash=_hash(raw_token),
        expires_at=_utcnow() + timedelta(seconds=settings.PUBLIC_CHAT_SESSION_TTL_SECONDS),
    ))
    return raw_token


def verify_and_rotate_public_chat_session(
    db: Session, conversation_id: int, token: Optional[str], rotate: bool = True
) -> Tuple[bool, Optional[str]]:
    """Validate one conversation-bound session, optionally rotating its token.

    The immediately preceding token remains valid for a short grace period so
    concurrent poll/send requests do not race each other.

    That grace was not enough on its own. Rotating on *reads* as well as writes
    meant the four-second poll and a slow send could rotate twice while both
    were in flight: the browser kept whichever reply landed last, the database
    held the other, and only one previous token is remembered — so every request
    after that was 403 and the conversation went silent with no error shown.

    Reads no longer rotate. They still prove possession and still push the
    expiry out; the new token is minted only when the patient actually sends
    something, which is serial by nature.
    """
    if not token:
        return False, None
    now = _utcnow()
    token_hash = _hash(token)
    session = db.query(PublicChatSession).filter(
        PublicChatSession.conversation_id == conversation_id,
        PublicChatSession.revoked_at.is_(None),
        PublicChatSession.expires_at >= now,
        (PublicChatSession.token_hash == token_hash)
        | ((PublicChatSession.previous_token_hash == token_hash) & (PublicChatSession.previous_expires_at >= now)),
    ).first()
    if not session:
        return False, None

    session.expires_at = now + timedelta(seconds=settings.PUBLIC_CHAT_SESSION_TTL_SECONDS)
    session.last_used_at = now
    if not rotate:
        # Hand back whatever the caller presented. It may be the grace-period
        # token rather than the current one, and telling the browser to keep
        # using that would expire under it in thirty seconds.
        return True, token if session.token_hash == token_hash else None

    rotated = secrets.token_urlsafe(32)
    session.previous_token_hash = session.token_hash
    session.previous_expires_at = now + timedelta(seconds=30)
    session.token_hash = _hash(rotated)
    return True, rotated
