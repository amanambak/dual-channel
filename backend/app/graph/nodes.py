import logging

from langgraph.config import get_stream_writer

from app.graph.state import TurnState
from app.llm.service import LLMService
from app.services.category_router import route_category as route_workflow_category
from app.services.contextual_extraction import normalize_contextual_extracted_fields
from app.services.field_resolver import build_resolved_field_state
from app.services.field_resolver import resolve_extracted_fields
from app.services.lead_detail_context import find_direct_lead_detail_answer
from app.services.next_action import select_next_action as select_workflow_next_action
from app.services.workflow_state import compute_workflow_state as compute_workflow

logger = logging.getLogger(__name__)


def build_turn_nodes(llm: LLMService):
    async def extract_schema(state: TurnState) -> dict:
        if not state.get("should_extract"):
            return {}

        current_fields = dict(state.get("known_fields", {}))
        extracted = await llm.extract_schema_values(
            utterance=state.get("utterance", ""),
            conversation_context=state.get("conversation_context", ""),
            known_fields=current_fields,
            agent_last_utterance=state.get("agent_last_utterance", ""),
            expected_field=state.get("expected_field"),
            active_category=state.get("active_category"),
            workflow_state=state.get("workflow_state", {}),
        )
        contextual_extracted = normalize_contextual_extracted_fields(
            extracted or {},
            expected_field=state.get("expected_field"),
            utterance=state.get("utterance", ""),
            agent_utterance=state.get("agent_last_utterance", ""),
        )
        if not contextual_extracted:
            return {}

        merged_fields = {**current_fields, **contextual_extracted}
        writer = get_stream_writer()
        writer({"type": "schema_extracted", "fields": contextual_extracted})
        return {"known_fields": merged_fields, "extracted_fields": contextual_extracted}

    async def route_category(state: TurnState) -> dict:
        known_fields = dict(state.get("known_fields", {}))
        field_state = build_resolved_field_state(
            existing=state.get("field_state", {}),
            lead_detail=state.get("lead_detail", {}),
            lead_facts=state.get("lead_facts", {}),
            extracted_fields=known_fields,
        )
        current_extracted = resolve_extracted_fields(state.get("extracted_fields", {}))
        route = route_workflow_category(
            utterance=state.get("utterance", ""),
            extracted_fields=current_extracted,
            field_state=field_state,
            previous_category=state.get("active_category"),
            agent_last_utterance=state.get("agent_last_utterance", ""),
            workflow_state=state.get("workflow_state", {}),
        )
        route_payload = route.to_dict()
        route_payload["previous_category"] = state.get("active_category")

        if _should_classify_category(route_payload, expected_field=state.get("expected_field")):
            try:
                classified = await llm.classify_category(
                    utterance=state.get("utterance", ""),
                    categories=route_payload.get("scores", {}),
                    deterministic_route=route_payload,
                    model_name=state.get("model_override"),
                )
            except Exception as exc:
                logger.warning("Category classifier fallback failed: %s", exc)
                classified = {}
            category = classified.get("category")
            if isinstance(category, str) and category in route_payload.get("scores", {}):
                route_payload = {
                    **route_payload,
                    "category": category,
                    "confidence": float(classified.get("confidence") or route_payload["confidence"]),
                    "reason": str(classified.get("reason") or route_payload["reason"]),
                    "llm_fallback_used": True,
                }

        return {"field_state": field_state, "category_route": route_payload}

    async def compute_workflow_state(state: TurnState) -> dict:
        route = state.get("category_route", {})
        active_category = route.get("category") or state.get("active_category")
        workflow_state = compute_workflow(
            state.get("field_state", {}),
            active_category=active_category,
        )
        return {
            "active_category": active_category,
            "workflow_state": workflow_state,
        }

    async def select_next_action(state: TurnState) -> dict:
        action = select_workflow_next_action(
            state.get("workflow_state", {}),
            state.get("category_route", {}),
            state.get("last_next_action") or {},
        )
        return {"next_action": action}

    async def generate_response(state: TurnState) -> dict:
        if not state.get("should_trigger"):
            return {}

        writer = get_stream_writer()
        direct_answer = find_direct_lead_detail_answer(
            state.get("utterance", ""),
            _combined_lead_sources(
                state.get("lead_detail", {}),
                state.get("lead_facts", {}),
            ),
        )
        if direct_answer:
            full_text = f"[SUGGESTION] {direct_answer}"
            writer(
                {
                    "type": "ai_chunk",
                    "utterance_id": state.get("utterance_id"),
                    "text": full_text,
                }
            )
            return {"raw_response": full_text}

        full_text = ""
        buffered_chunks: list[str] = []
        started_streaming = False
        skip_prefix = "[SKIP]"
        valid_prefixes = ("[SUMMARY]", "[SUGGESTION]", "[INFO]")

        def _release_buffer() -> None:
            nonlocal started_streaming
            if started_streaming:
                return
            for buffered_chunk in buffered_chunks:
                writer(
                    {
                        "type": "ai_chunk",
                        "utterance_id": state.get("utterance_id"),
                        "text": buffered_chunk,
                    }
                )
            buffered_chunks.clear()
            started_streaming = True

        async for chunk in llm.stream_reply(
            state.get("utterance", ""),
            state.get("conversation_context", ""),
            state.get("model_override"),
            customer_last_utterance=state.get("customer_last_utterance", ""),
            agent_last_utterance=state.get("agent_last_utterance", ""),
            context_summary=state.get("context_summary", ""),
            known_entities=state.get("known_fields", {}),
            last_suggestion=state.get("last_suggestion", ""),
            priority_missing_fields=state.get("lead_priority_missing_fields", []),
            next_action=state.get("next_action", {}),
            workflow_state=state.get("workflow_state", {}),
            active_category=state.get("active_category"),
        ):
            full_text += chunk
            if not started_streaming:
                buffered_chunks.append(chunk)
                normalized = "".join(buffered_chunks).lstrip()
                upper_normalized = normalized.upper()
                if upper_normalized == skip_prefix:
                    return {}
                if any(prefix.startswith(upper_normalized) for prefix in valid_prefixes):
                    if any(upper_normalized.startswith(prefix) for prefix in valid_prefixes):
                        _release_buffer()
                    continue
                if any(upper_normalized.startswith(prefix) for prefix in valid_prefixes):
                    _release_buffer()
                    continue
                if len(normalized) > len(skip_prefix) and not any(
                    prefix.startswith(upper_normalized) for prefix in valid_prefixes
                ):
                    _release_buffer()
            if started_streaming:
                writer(
                    {
                        "type": "ai_chunk",
                        "utterance_id": state.get("utterance_id"),
                        "text": chunk,
                    }
                )

        # [SKIP] means the model has nothing new to contribute — suppress the event.
        if not full_text or full_text.strip().upper().startswith("[SKIP]"):
            return {}

        return {"raw_response": full_text}

    return {
        "extract_schema": extract_schema,
        "route_category": route_category,
        "compute_workflow_state": compute_workflow_state,
        "select_next_action": select_next_action,
        "generate_response": generate_response,
    }


def _combined_lead_sources(lead_detail: dict | None, lead_facts: dict | None) -> dict:
    combined: dict = {}
    if isinstance(lead_facts, dict):
        combined.update(lead_facts)
    if isinstance(lead_detail, dict):
        combined.update(lead_detail)
    return combined


def _should_classify_category(
    route_payload: dict,
    *,
    expected_field: str | None,
) -> bool:
    if expected_field:
        return False
    if not route_payload.get("needs_llm"):
        return False
    scores = route_payload.get("scores") or {}
    if not isinstance(scores, dict) or not scores:
        return False
    ranked = sorted(
        (float(score or 0.0) for score in scores.values()),
        reverse=True,
    )
    top_score = ranked[0]
    second_score = ranked[1] if len(ranked) > 1 else 0.0
    return top_score < 0.75 and (top_score - second_score) < 0.20
