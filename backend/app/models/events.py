from typing import Any

from pydantic import BaseModel, Field


class TranscriptEvent(BaseModel):
    type: str = "transcript_update"
    transcript: str
    isFinal: bool
    metadata: dict[str, Any] = Field(default_factory=dict)
    speaker: str | None = None


class UtteranceCommittedEvent(BaseModel):
    type: str = "utterance_committed"
    utteranceId: str
    text: str
    speaker: str | None = None


class AIChunkEvent(BaseModel):
    type: str = "ai_response_chunk"
    utteranceId: str
    text: str


class AIDoneEvent(BaseModel):
    type: str = "ai_response_done"
    utteranceId: str
    fullText: str
    badgeType: str


class ErrorEvent(BaseModel):
    type: str = "error"
    source: str
    message: str
