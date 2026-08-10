import pytest

from backend.app.services import ai_engine


@pytest.fixture(autouse=True)
def never_call_the_real_llm(monkeypatch):
    """No test may reach OpenAI.

    Several tests drive process_chat_message end to end. With OPENAI_API_KEY set
    in a developer's .env those calls go out for real: the suite gets slow, costs
    money on every run, and the assertions start depending on whatever the model
    happened to say that day. The keyword mock is deterministic and reads from
    the same clinic data, which is what the tests are actually about.
    """
    monkeypatch.setattr(ai_engine, "openai_client", None)
