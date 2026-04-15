from pydantic import BaseModel, Field


class ConversationMessage(BaseModel):
    type: str
    text: str
    utterance_id: str | None = None
    badge_type: str | None = None


class SessionState(BaseModel):
    session_id: str
    current_segments: list[str] = Field(default_factory=list)
    messages: list[ConversationMessage] = Field(default_factory=list)
    extracted_fields: dict[str, str] = Field(default_factory=dict)
