import logging
from collections.abc import Callable

from app.models.events import AIDoneEvent
from app.models.events import AIChunkEvent
from app.models.events import ErrorEvent
from app.models.session import ConversationMessage
from app.services.agent_question_context import current_spoken_expected_field
from app.services.agent_question_context import stamp_next_action
from app.services.contextual_extraction import normalize_contextual_extracted_fields
from app.services.field_resolver import build_resolved_field_state
from app.services.session_response import normalize_ai_response
from app.services.schema_normalizer import derive_extracted_fields

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
    model_override: str | None,
    should_extract: bool,
    should_trigger: bool,
) -> None:
    logger.info("run_turn_graph CALLED for: %.50s", utterance)

    async with session.ai_lock:
        conversation_context = session.build_recent_conversation_context()
        expected_field = _current_expected_field(session)
        turn_state = {
            "session_id": session_id,
            "utterance_id": utterance_id,
            "utterance": utterance,
            "speaker": speaker,
            "conversation_context": conversation_context,
            "known_fields": dict(session.state.extracted_fields),
            "should_extract": should_extract,
            "should_trigger": should_trigger,
            "model_override": model_override,
            "customer_last_utterance": session.state.customer_last_utterance,
            "agent_last_utterance": session.state.agent_last_utterance,
            "context_summary": session.state.rolling_summary or conversation_context,
            "last_suggestion": session.state.last_suggestion,
            "lead_priority_missing_fields": list(session.state.lead_priority_missing_fields),
            "lead_detail": dict(session.state.lead_detail),
            "lead_facts": dict(session.state.lead_facts),
            "field_state": dict(session.state.resolved_field_state),
            "active_category": session.state.active_category,
            "category_route": dict(session.state.category_route),
            "workflow_state": dict(session.state.workflow_state),
            "last_next_action": dict(session.state.last_next_action),
            "expected_field": expected_field,
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
                                normalize_contextual_extracted_fields(
                                    fields,
                                    expected_field=expected_field,
                                    utterance=utterance,
                                    agent_utterance=session.state.agent_last_utterance,
                                )
                            )
                            derive_extracted_fields(session.state.extracted_fields)
                elif chunk_type == "updates":
                    updates = chunk.get("data", {})
                    if isinstance(updates, dict):
                        for node_update in updates.values():
                            if not isinstance(node_update, dict):
                                continue
                            extracted = node_update.get("extracted_fields")
                            if isinstance(extracted, dict):
                                session.state.extracted_fields.update(
                                    normalize_contextual_extracted_fields(
                                        extracted,
                                        expected_field=expected_field,
                                        utterance=utterance,
                                        agent_utterance=session.state.agent_last_utterance,
                                    )
                                )
                                derive_extracted_fields(session.state.extracted_fields)
                            raw_response = node_update.get("raw_response")
                            if isinstance(raw_response, str) and raw_response:
                                full_text = raw_response
                            field_state = node_update.get("field_state")
                            if isinstance(field_state, dict):
                                session.state.resolved_field_state = field_state
                            active_category = node_update.get("active_category")
                            if isinstance(active_category, str):
                                session.state.active_category = active_category
                            category_route = node_update.get("category_route")
                            if isinstance(category_route, dict):
                                session.state.category_route = category_route
                            workflow_state = node_update.get("workflow_state")
                            if isinstance(workflow_state, dict):
                                session.state.workflow_state = workflow_state
                            next_action = node_update.get("next_action")
                            if isinstance(next_action, dict):
                                session.state.last_next_action = stamp_next_action(
                                    next_action,
                                    session.state,
                                )
        except Exception as exc:
            logger.error(f"LangGraph error: {exc}")
            await send_model(ErrorEvent(source="LangGraph", message=str(exc)))
            return

        if not full_text:
            return

        logger.info("RAW LLM RESPONSE: %.500s", full_text)
        full_text = normalize_ai_response(session, full_text, utterance)
        session.state.resolved_field_state = build_resolved_field_state(
            existing=session.state.resolved_field_state,
            lead_detail=session.state.lead_detail,
            lead_facts=session.state.lead_facts,
            extracted_fields=session.state.extracted_fields,
        )
        if not full_text:
            return
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


def _current_expected_field(session) -> str | None:
    return current_spoken_expected_field(session.state)
