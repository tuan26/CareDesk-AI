"""Feature flags: turn things off without deleting them.

The point of the table is that switching a feature back on later is a flag flip
rather than a rebuild, so the tests care about two things — the resolution order
(clinic beats vendor beats shipped default) and the fact that a disabled area is
genuinely unreachable rather than merely hidden in the UI.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models.models import AutomationRule, Clinic, FeatureFlag
from backend.app.services.events import DEFAULT_RULES, seed_default_automations
from backend.app.services.features import (
    CHAIN_CONSOLE, COPILOT, DEFAULTS, FACEBOOK_CAPI, MULTILANG, all_flags,
    is_enabled, set_flag,
)

engine = create_engine("sqlite:///:memory:")
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db():
    Base.metadata.create_all(bind=engine)
    s = TestingSessionLocal()
    yield s
    s.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def clinic(db):
    c = Clinic(name="CareDesk", is_active=True)
    db.add(c)
    db.commit()
    return c


def test_everything_optional_ships_off(db, clinic):
    """The first release sells one promise. Each of these widens it."""
    for key in (CHAIN_CONSOLE, MULTILANG, COPILOT, FACEBOOK_CAPI):
        assert DEFAULTS[key] is False
        assert is_enabled(db, clinic.id, key) is False


def test_a_clinic_setting_beats_the_vendor_default(db, clinic):
    set_flag(db, None, MULTILANG, True)          # vendor-wide
    assert is_enabled(db, clinic.id, MULTILANG) is True

    set_flag(db, clinic.id, MULTILANG, False)    # this clinic opts out
    assert is_enabled(db, clinic.id, MULTILANG) is False
    assert is_enabled(db, None, MULTILANG) is True, "other clinics unaffected"


def test_the_vendor_default_applies_to_clinics_with_no_row(db, clinic):
    set_flag(db, None, COPILOT, True)
    assert is_enabled(db, clinic.id, COPILOT) is True


def test_setting_a_flag_twice_updates_rather_than_duplicates(db, clinic):
    set_flag(db, clinic.id, COPILOT, True)
    set_flag(db, clinic.id, COPILOT, False)
    assert db.query(FeatureFlag).filter(FeatureFlag.clinic_id == clinic.id).count() == 1
    assert is_enabled(db, clinic.id, COPILOT) is False


def test_an_unknown_key_is_refused_on_write_and_false_on_read(db, clinic):
    with pytest.raises(ValueError):
        set_flag(db, clinic.id, "khong_ton_tai", True)
    assert is_enabled(db, clinic.id, "khong_ton_tai") is False


def test_all_flags_covers_every_declared_key(db, clinic):
    assert set(all_flags(db, clinic.id)) == set(DEFAULTS)


# --- the two automations that ship switched off ------------------------------

SPAM_PRONE = {
    "Đánh thức khách cũ (6 tháng)",
    "Follow-up khách hỏi giá (5 ngày - ưu đãi)",
}


def test_the_spam_prone_automations_are_seeded_disabled(db, clinic):
    """Everything else is on: these two reach the whole back catalogue or nudge
    a second time about a promotion, and both risk a spam report against a Zalo
    OA that has no history yet."""
    seed_default_automations(db, clinic.id)

    rules = {r.name: r.enabled for r in db.query(AutomationRule).all()}
    assert len(rules) == len(DEFAULT_RULES)
    for name in SPAM_PRONE:
        assert rules[name] is False, f"{name} phải tắt mặc định"
    for name, enabled in rules.items():
        if name not in SPAM_PRONE:
            assert enabled is True, f"{name} là kịch bản lõi, phải bật"


def test_the_clinic_can_still_turn_them_on(db, clinic):
    """Off by default, not removed — the Automation screen flips them."""
    seed_default_automations(db, clinic.id)
    rule = db.query(AutomationRule).filter(
        AutomationRule.name == "Đánh thức khách cũ (6 tháng)"
    ).first()
    rule.enabled = True
    db.commit()
    db.refresh(rule)
    assert rule.enabled is True
