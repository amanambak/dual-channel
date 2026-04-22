import asyncio
import logging
import time
import uuid

from app.models.events import TranscriptEvent
from app.models.events import UtteranceCommittedEvent
from app.models.session import ConversationMessage
from app.services.session_text import (
    get_average_confidence,
    should_extract_schema_fields,
)

logger = logging.getLogger(__name__)


async def finalize_utterance(session) -> None:
    logger.info(
        f"finalize_utterance: finalized_segments={session.finalized_segments}, current_segments={len(session.state.current_segments)}"
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

    session.last_should_extract = should_extract_schema_fields(text, average_confidence)

    logger.info(f"ABOUT TO CHECK TRIGGER for: {text[:30]}")
    should_trigger = False
    try:
        new_stage = session.detect_call_stage(text, speaker)
        if new_stage != session.state.call_stage:
            session.state.call_stage = new_stage

        await session.update_rolling_summary(text, speaker)
        should_trigger = session.should_invoke_llm(text, average_confidence, speaker)
        logger.info(
            f"LLM trigger check: text={text[:30]}, confidence={average_confidence}, speaker={speaker}, triggered={should_trigger}"
        )
    except Exception as exc:
        logger.error(f"Error in trigger check: {exc}", exc_info=True)

    if session.last_should_extract or should_trigger:
        session.last_llm_invoked_at = time.monotonic()
        asyncio.create_task(
            session.run_turn_graph(
                utterance=text,
                utterance_id=utterance_id,
                speaker=speaker,
                should_extract=session.last_should_extract,
                should_trigger=should_trigger,
            )
        )
