import time

from app.services.session_text import decide_turn_action


def test_agent_turn_does_not_trigger_extraction_or_reply():
    decision = decide_turn_action(
        utterance="Sir loan amount kitna chahiye?",
        average_confidence=0.9,
        speaker="1",
        last_llm_invoked_at=0.0,
        cooldown=3.0,
    )

    assert decision.run_extraction is False
    assert decision.run_reply is False
    assert decision.reason == "agent_context_only"


def test_customer_info_runs_extraction_inside_reply_cooldown():
    decision = decide_turn_action(
        utterance="loan amount 25 lakh cibil score 750",
        average_confidence=0.55,
        speaker="0",
        last_llm_invoked_at=time.monotonic(),
        cooldown=3.0,
    )

    assert decision.run_extraction is True
    assert decision.run_reply is False
    assert decision.reason == "customer_extract_only"


def test_customer_info_runs_extraction_and_reply_outside_cooldown():
    decision = decide_turn_action(
        utterance="loan amount 25 lakh cibil score 750",
        average_confidence=0.9,
        speaker="0",
        last_llm_invoked_at=time.monotonic() - 5.0,
        cooldown=3.0,
    )

    assert decision.run_extraction is True
    assert decision.run_reply is True
    assert decision.reason == "customer_extract_and_reply"


def test_filler_turn_is_skipped():
    decision = decide_turn_action(
        utterance="haan",
        average_confidence=0.9,
        speaker="0",
        last_llm_invoked_at=0.0,
        cooldown=3.0,
    )

    assert decision.run_extraction is False
    assert decision.run_reply is False
    assert decision.reason == "noise_or_filler"
