from pydantic import BaseModel, Field


class ConversationMessage(BaseModel):
    type: str
    text: str
    utterance_id: str | None = None
    badge_type: str | None = None
    speaker: str | None = None


class SessionState(BaseModel):
    session_id: str
    current_segments: list[tuple[str, str | None]] = Field(default_factory=list)
    messages: list[ConversationMessage] = Field(default_factory=list)
    extracted_fields: dict[str, str] = Field(default_factory=dict)
    customer_last_utterance: str = Field(default="")
    agent_last_utterance: str = Field(default="")
    call_stage: str = Field(default="unknown")
    sentiment: str = Field(default="neutral")
    rolling_summary: str = Field(default="")
    customer_history: list[str] = Field(default_factory=list)
    agent_history: list[str] = Field(default_factory=list)
