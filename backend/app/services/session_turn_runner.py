import logging
from collections.abc import Callable

from app.models.events import AIDoneEvent
from app.models.events import AIChunkEvent
from app.models.events import ErrorEvent
from app.models.session import ConversationMessage
from app.services.session_response import normalize_ai_response

logger = logging.getLogger(__name__)


async def run_turn_graph(
    *,
    turn_graph,
    send_model: Callable,
    session,
    session_id: str,
    utterance: str,
    utterance_id: str,
    speaker: str | None,
    schema_prompt: str,
    schema_fields: dict[str, str],
    model_override: str | None,
    should_extract: bool,
    should_trigger: bool,
) -> None:
    logger.info(f"run_turn_graph CALLED for: {utterance[:50]}")

    async with session.ai_lock:
        conversation_context = session.build_recent_conversation_context()
        turn_state = {
            "session_id": session_id,
            "utterance_id": utterance_id,
            "utterance": utterance,
            "speaker": speaker,
            "conversation_context": conversation_context,
            "schema_prompt": schema_prompt,
            "schema_fields": schema_fields,
            "known_fields": dict(session.state.extracted_fields),
            "should_extract": should_extract,
            "should_trigger": should_trigger,
            "model_override": model_override,
            "customer_last_utterance": session.state.customer_last_utterance,
            "agent_last_utterance": session.state.agent_last_utterance,
            "context_summary": session.state.rolling_summary or conversation_context,
        }

        full_text = ""
        try:
            async for chunk in turn_graph.stream_turn(turn_state, thread_id=session_id):
                chunk_type = chunk.get("type")
                if chunk_type == "custom":
                    data = chunk.get("data", {})
                    if isinstance(data, dict) and data.get("type") == "ai_chunk":
                        text = str(data.get("text", ""))
                        if text:
                            full_text += text
                            await send_model(
                                AIChunkEvent(utteranceId=utterance_id, text=text)
                            )
                    if isinstance(data, dict) and data.get("type") == "schema_extracted":
                        fields = data.get("fields", {})
                        if isinstance(fields, dict):
                            session.state.extracted_fields.update(
                                {
                                    str(key): str(value)
                                    for key, value in fields.items()
                                    if value is not None and str(value).strip()
                                }
                            )
                elif chunk_type == "updates":
                    updates = chunk.get("data", {})
                    if isinstance(updates, dict):
                        for node_update in updates.values():
                            if not isinstance(node_update, dict):
                                continue
                            extracted = node_update.get("extracted_fields")
                            if isinstance(extracted, dict):
                                session.state.extracted_fields.update(
                                    {
                                        str(key): str(value)
                                        for key, value in extracted.items()
                                        if value is not None and str(value).strip()
                                    }
                                )
                            raw_response = node_update.get("raw_response")
                            if isinstance(raw_response, str) and raw_response:
                                full_text = raw_response
        except Exception as exc:
            logger.error(f"LangGraph error: {exc}")
            await send_model(ErrorEvent(source="LangGraph", message=str(exc)))
            return

        if not full_text:
            return

        logger.info(f"RAW LLM RESPONSE: {full_text[:500]}")
        full_text = normalize_ai_response(session, full_text, utterance)
        session.state.messages.append(
            ConversationMessage(
                type="ai",
                text=full_text,
                utterance_id=utterance_id,
                badge_type="suggestion",
            )
        )
        await send_model(
            AIDoneEvent(
                utteranceId=utterance_id,
                fullText=full_text,
                badgeType="suggestion",
            )
        )
