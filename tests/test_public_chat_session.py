from backend.app.services.public_chat_session import create_public_chat_token, verify_public_chat_token


def test_public_chat_token_is_bound_to_its_conversation():
    token = create_public_chat_token(31, ttl_seconds=60)
    assert verify_public_chat_token(31, token) is True
    assert verify_public_chat_token(32, token) is False


def test_public_chat_token_rejects_tampering_and_expiry():
    token = create_public_chat_token(31, ttl_seconds=60)
    assert verify_public_chat_token(31, token + "x") is False

    expired = create_public_chat_token(31, ttl_seconds=-1)
    assert verify_public_chat_token(31, expired) is False
