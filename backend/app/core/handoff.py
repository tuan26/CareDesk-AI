"""Why a human was called, and what the assistant may do while it waits.

"Handoff" was one flag, and it meant two very different situations:

  * a person is in the conversation right now — the assistant must stay out of
    the way, or the patient gets two voices answering at once;
  * a person has been *asked for* and has not arrived — nights, weekends, a busy
    afternoon. This can last hours.

The second was treated like the first, so every message the patient sent while
waiting was stored and answered with nothing at all. They asked "có những gói
khám nào tôi có thể đặt được" — a question the service list answers — twice, to
silence, and left.

Silence is not neutral. It reads as broken, and a patient who thinks the clinic
is broken does not ring back. So while the queue is unattended the assistant
keeps answering — except where answering is the actual danger.
"""

#: A safety rule matched: self-harm, an emergency, something clinical. The
#: assistant must not keep talking, whatever else the patient asks. This is the
#: one case where silence beats a plausible sentence.
SAFETY = "safety"

#: The clinic's monthly AI allowance is gone. Answering anyway is the vendor
#: giving away what it just declined to sell.
QUOTA = "quota"

#: A low review score, routed to a person on purpose.
REVIEW = "review_escalation"

#: The model was unsure, said so, or produced a booking claim that was not true;
#: or the LLM itself is failing. The patient's *next* question may be perfectly
#: ordinary, and refusing to answer it helps nobody.
UNSURE = "model_unsure"
PHRASE = "phrase_match"
FABRICATED = "fabricated_booking"
LLM_DOWN = "llm_unavailable"

#: Reasons that silence the assistant until a human takes over.
MUTING_REASONS = frozenset({SAFETY, QUOTA, REVIEW})


def assistant_may_reply(status: str, reason: str | None) -> bool:
    """May the assistant answer this message?

    `agent_active` always means no: a receptionist is typing, and two answers to
    one question is worse than a slow one.
    """
    if status == "agent_active":
        return False
    if status != "handoff_requested":
        return True
    return reason not in MUTING_REASONS
