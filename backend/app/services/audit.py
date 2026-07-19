from typing import Optional
from sqlalchemy.orm import Session
from backend.app.models.models import AuditLog


def log_action(db: Session, user_id: Optional[int], action: str, details: str = None):
    """
    Persist an audit trail entry. Commits together with the caller's transaction
    (caller must commit); use commit=True for standalone logging.
    """
    entry = AuditLog(user_id=user_id, action=action, details=details)
    db.add(entry)
    return entry
