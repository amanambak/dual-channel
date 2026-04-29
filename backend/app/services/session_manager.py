import asyncio
import logging
import uuid

from fastapi import WebSocket

from app.graph.service import TurnGraphService
from app.models.session import SessionState
from app.services.schema_registry import get_schema_registry
from app.services.session_finalize import finalize_utterance as finalize_utterance_helper
from app.services.session_text import (
    build_fallback_summary,
    build_known_fields_text,
    build_recent_conversation_context,
    convert_summary_to_hinglish,
    decide_turn_action,
    detect_call_stage,
    get_average_confidence,
    looks_like_noise_or_filler,
    normalize_confidence,
    normalize_text,
    should_capture_final_segment,
    should_invoke_llm,
)
from app.services.session_turn_runner import run_turn_graph as run_turn_graph_helper
from app.services import session_transport

logger = logging.getLogger(__name__)


class SessionRuntime:
    def __init__(self, websocket: WebSocket) -> None:
        self.websocket = websocket
        self.session_id = str(uuid.uuid4())
        self.state = SessionState(session_id=self.session_id)
        self.deepgrams = {}
        self.turn_graph = TurnGraphService()
        self.schema_registry = get_schema_registry()
        self.deepgram_tasks: dict[str, asyncio.Task] = {}
        self.deepgram_keepalive_tasks: dict[str, asyncio.Task] = {}
        self.ai_lock = asyncio.Lock()
        self.closed = False
        self.connection_closed = False
        self.model_override: str | None = None
        self.finalized_segments = False
        self.finalize_task: asyncio.Task | None = None
        self.finalize_delay_seconds = 0.45
        self.pending_incomplete_utterance = ""
        self.current_segment_confidences: list[float] = []
        self.last_llm_invoked_at = 0.0
        self.min_llm_interval_seconds = 3.0
        self.last_should_extract = False

    async def run(self) -> None:
        await session_transport.run(self)

    async def handle_text_message(self, raw_message: str) -> None:
        await session_transport.handle_text_message(self, raw_message)

    async def read_deepgram(self, channel: str) -> None:
        await session_transport.read_deepgram(self, channel)

    async def handle_deepgram_message(self, data: dict) -> None:
        await session_transport.handle_deepgram_message(self, data)

    async def finalize_utterance(self) -> None:
        await finalize_utterance_helper(self)

    def build_recent_conversation_context(self, limit: int = 8) -> str:
        return build_recent_conversation_context(self.state, limit=limit)

    def build_known_fields_text(self, limit: int = 8) -> str:
        return build_known_fields_text(self.state.extracted_fields, limit=limit)

    def build_fallback_summary(self, utterance: str) -> str:
        return build_fallback_summary(utterance)

    def convert_summary_to_hinglish(self, summary: str) -> str:
        return convert_summary_to_hinglish(summary)

    def detect_call_stage(self, utterance: str, speaker: str | None) -> str:
        return detect_call_stage(utterance, self.state)

    async def update_rolling_summary(self, utterance: str, speaker: str | None) -> None:
        if not utterance or len(utterance) < 10:
            return
        preview = utterance[:100]
        if self.state.rolling_summary:
            self.state.rolling_summary = f"{self.state.rolling_summary} | {preview}"
        else:
            self.state.rolling_summary = preview
        if len(self.state.rolling_summary) > 500:
            self.state.rolling_summary = self.state.rolling_summary[-400:]

    def should_invoke_llm(
        self, utterance: str, average_confidence: float, speaker: str | None = None
    ) -> bool:
        return should_invoke_llm(
            utterance,
            average_confidence,
            self.last_llm_invoked_at,
            self.min_llm_interval_seconds,
        )

    def should_extract_schema_fields(
        self, utterance: str, average_confidence: float
    ) -> bool:
        return decide_turn_action(
            utterance,
            average_confidence,
            "0",
            self.last_llm_invoked_at,
            self.min_llm_interval_seconds,
        ).run_extraction

    def should_capture_final_segment(
        self, transcript: str, confidence: float | None
    ) -> bool:
        return should_capture_final_segment(transcript, confidence)

    def normalize_confidence(self, confidence: float | None) -> float:
        return normalize_confidence(confidence)

    def get_average_confidence(self) -> float:
        return get_average_confidence(self.current_segment_confidences)

    def looks_like_noise_or_filler(self, normalized: str) -> bool:
        return looks_like_noise_or_filler(normalized)

    def is_incomplete_utterance(self, utterance: str) -> bool:
        normalized = normalize_text(utterance)
        if not normalized:
            return False
        trailing_phrases = (
            "to",
            "toh",
            "ki",
            "aur",
            "or",
            "par",
            "lekin",
            "magar",
            "kyunki",
            "kyuki",
            "jaise",
            "aapne",
            "maine",
            "humne",
            "usme",
            "usmein",
            "isme",
            "ismein",
            "phir",
            "fir",
            "then",
            "matlab",
            "because",
        )
        return any(
            normalized.endswith(f" {phrase}") or normalized == phrase
            for phrase in trailing_phrases
        )

    async def run_turn_graph(
        self,
        utterance: str,
        utterance_id: str,
        speaker: str | None,
        should_extract: bool,
        should_trigger: bool,
    ) -> None:
        await run_turn_graph_helper(
            turn_graph=self.turn_graph,
            send_model=self.send_model,
            session=self,
            session_id=self.session_id,
            utterance=utterance,
            utterance_id=utterance_id,
            speaker=speaker,
            schema_prompt=self.schema_registry.format_for_prompt(),
            schema_fields=self.schema_registry.fields,
            model_override=self.model_override,
            should_extract=should_extract,
            should_trigger=should_trigger,
        )

    async def generate_summary(self) -> dict:
        return {"customer_info": dict(self.state.extracted_fields)}

    async def send_model(self, model) -> None:
        await self.send_json(model.model_dump())

    async def send_json(self, payload: dict) -> None:
        if self.closed or self.connection_closed:
            return
        await self.websocket.send_json(payload)

    def _schedule_finalize(self) -> None:
        self._cancel_finalize_task()
        self.finalize_task = asyncio.create_task(self._debounced_finalize())

    def _cancel_finalize_task(self) -> None:
        if self.finalize_task is not None and not self.finalize_task.done():
            self.finalize_task.cancel()
        self.finalize_task = None

    async def _debounced_finalize(self) -> None:
        try:
            await asyncio.sleep(self.finalize_delay_seconds)
            await self.finalize_utterance()
        except asyncio.CancelledError:
            return

    async def close(self) -> None:
        await session_transport.close(self)


class SessionManager:
    """Registry that tracks active WebSocket sessions.

    Each ``SessionRuntime`` is keyed by its UUID session_id.
    Sessions are removed upon close to avoid unbounded memory growth.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, SessionRuntime] = {}

    async def create_session(self, websocket: WebSocket) -> SessionRuntime:
        session = SessionRuntime(websocket)
        self._sessions[session.session_id] = session
        return session

    def get_session(self, session_id: str) -> SessionRuntime | None:
        return self._sessions.get(session_id)

    async def close_session(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session is not None:
            await session.close()
