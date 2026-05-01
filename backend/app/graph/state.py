from typing import TypedDict


class TurnState(TypedDict, total=False):
    session_id: str
    utterance_id: str
    utterance: str
    speaker: str | None
    conversation_context: str
    schema_prompt: str
    schema_fields: dict[str, str]
    known_fields: dict[str, str]
    should_extract: bool
    should_trigger: bool
    model_override: str | None
    customer_last_utterance: str
    agent_last_utterance: str
    context_summary: str
    last_suggestion: str  # last AI suggestion sent — model must not repeat it
    lead_priority_missing_fields: list[dict]
    extracted_fields: dict[str, str]
    raw_response: str

