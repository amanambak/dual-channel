from langgraph.config import get_stream_writer

from app.llm.service import LLMService
from app.graph.state import TurnState


def build_turn_nodes(llm: LLMService):
    async def extract_schema(state: TurnState) -> dict:
        if not state.get("should_extract"):
            return {}

        current_fields = dict(state.get("known_fields", {}))
        extracted = await llm.extract_schema_values(
            utterance=state.get("utterance", ""),
            conversation_context=state.get("conversation_context", ""),
            known_fields=current_fields,
            schema_fields=state.get("schema_fields", {}),
            schema_prompt=state.get("schema_prompt", ""),
        )
        if not extracted:
            return {}

        merged_fields = {**current_fields, **extracted}
        writer = get_stream_writer()
        writer({"type": "schema_extracted", "fields": extracted})
        return {"known_fields": merged_fields, "extracted_fields": extracted}

    async def generate_response(state: TurnState) -> dict:
        if not state.get("should_trigger"):
            return {}

        writer = get_stream_writer()
        full_text = ""

        async for chunk in llm.stream_reply(
            state.get("utterance", ""),
            state.get("conversation_context", ""),
            state.get("model_override"),
            customer_last_utterance=state.get("customer_last_utterance", ""),
            agent_last_utterance=state.get("agent_last_utterance", ""),
            context_summary=state.get("context_summary", ""),
            known_entities=state.get("known_fields", {}),
        ):
            full_text += chunk
            writer(
                {
                    "type": "ai_chunk",
                    "utterance_id": state.get("utterance_id"),
                    "text": chunk,
                }
            )

        return {"raw_response": full_text}

    return {
        "extract_schema": extract_schema,
        "generate_response": generate_response,
    }
