import asyncio
import logging
import time
import uuid

from app.models.events import TranscriptEvent
from app.models.events import UtteranceCommittedEvent
from app.models.session import ConversationMessage
from app.services.session_text import (
    build_turn_dedupe_key,
    decide_turn_action,
    get_average_confidence,
)

logger = logging.getLogger(__name__)


async def finalize_utterance(session) -> None:
    logger.info(
        "finalize_utterance: finalized_segments=%s, current_segments=%d",
        session.finalized_segments,
        len(session.state.current_segments),
    )
    if not session.finalized_segments or not session.state.current_segments:
        return

    text = " ".join(seg[0] for seg in session.state.current_segments).strip()
    speaker = session.state.current_segments[0][1] if session.state.current_segments else None
    session.state.current_segments = []
    session.finalized_segments = False
    average_confidence = get_average_confidence(session.current_segment_confidences)
    session.current_segment_confidences = []

    if not text:
        return

    if session.pending_incomplete_utterance:
        text = f"{session.pending_incomplete_utterance} {text}".strip()
        session.pending_incomplete_utterance = ""

    utterance_id = f"utt-{uuid.uuid4().hex[:12]}"
    if speaker == "0":
        session.state.customer_last_utterance = text
        session.state.customer_history.append(text)
        if len(session.state.customer_history) > 20:
            session.state.customer_history.pop(0)
    elif speaker == "1":
        session.state.agent_last_utterance = text
        session.state.agent_history.append(text)
        if len(session.state.agent_history) > 20:
            session.state.agent_history.pop(0)

    session.state.messages.append(
        ConversationMessage(type="user", text=text, utterance_id=utterance_id, speaker=speaker)
    )
    if len(session.state.messages) > 1000:
        session.state.messages.pop(0)
    await session.send_model(
        UtteranceCommittedEvent(utteranceId=utterance_id, text=text, speaker=speaker)
    )

    logger.info("ABOUT TO CHECK TRIGGER for: %.30s", text)
    decision = decide_turn_action(
        utterance=text,
        average_confidence=average_confidence,
        speaker=speaker,
        last_llm_invoked_at=session.last_llm_invoked_at,
        cooldown=session.min_llm_interval_seconds,
    )
    session.last_should_extract = decision.run_extraction
    try:
        new_stage = session.detect_call_stage(text, speaker)
        if new_stage != session.state.call_stage:
            session.state.call_stage = new_stage

        await session.update_rolling_summary(text, speaker)
        logger.info(
            "Turn decision: text=%.30s, confidence=%.2f, speaker=%s, extract=%s, reply=%s, reason=%s",
            text,
            average_confidence,
            speaker,
            decision.run_extraction,
            decision.run_reply,
            decision.reason,
        )
    except Exception as exc:
        logger.error("Error in trigger check: %s", exc, exc_info=True)

    if decision.run_extraction or decision.run_reply:
        dedupe_key = build_turn_dedupe_key(text, speaker)
        now = time.monotonic()
        if (
            session.state.last_triggered_utterance_key == dedupe_key
            and now - session.state.last_triggered_utterance_at < 25.0
        ):
            logger.info(
                "Skipping duplicate LLM turn for speaker=%s text=%.50s",
                speaker,
                text,
            )
            return
        session.state.last_triggered_utterance_key = dedupe_key
        session.state.last_triggered_utterance_at = now
        if decision.run_reply:
            session.last_llm_invoked_at = time.monotonic()
        asyncio.create_task(
            session.run_turn_graph(
                utterance=text,
                utterance_id=utterance_id,
                speaker=speaker,
                should_extract=decision.run_extraction,
                should_trigger=decision.run_reply,
            )
        )
