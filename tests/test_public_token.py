from backend.app.services.reminder import make_public_token, verify_public_token


def test_token_roundtrip():
    token = make_public_token(123)
    assert verify_public_token(123, token) is True


def test_token_wrong_appointment():
    token = make_public_token(123)
    assert verify_public_token(124, token) is False


def test_token_tampered():
    assert verify_public_token(123, "abc123") is False
    assert verify_public_token(123, "") is False
    assert verify_public_token(123, None) is False
