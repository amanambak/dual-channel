import asyncio
import json
import logging
import re
import time
import uuid

from fastapi import WebSocket, WebSocketDisconnect

from app.models.events import AIDoneEvent
from app.models.events import AIChunkEvent
from app.models.events import ErrorEvent
from app.models.events import TranscriptEvent
from app.models.events import UtteranceCommittedEvent
from app.models.session import ConversationMessage
from app.models.session import SessionState
from app.services.deepgram_client import DeepgramClient
from app.services.gemini_client import GeminiClient
from app.services.schema_registry import get_schema_registry

logger = logging.getLogger(__name__)


class SessionRuntime:
    def __init__(self, websocket: WebSocket) -> None:
        self.websocket = websocket
        self.session_id = str(uuid.uuid4())
        self.state = SessionState(session_id=self.session_id)
        self.deepgrams: dict[str, DeepgramClient] = {}
        self.gemini = GeminiClient()
        self.schema_registry = get_schema_registry()
        self.deepgram_tasks: dict[str, asyncio.Task] = {}
        self.ai_lock = asyncio.Lock()
        self.closed = False
        self.connection_closed = False
        self.gemini_model_override: str | None = None
        self.finalized_segments = False
        self.finalize_task: asyncio.Task | None = None
        self.finalize_delay_seconds = 0.45
        self.pending_incomplete_utterance = ""
        self.current_segment_confidences: list[float] = []
        self.last_llm_invoked_at = 0.0
        self.min_llm_interval_seconds = 8.0
        self.min_average_confidence = 0.72
        self.normalize_regex1 = re.compile(r"\s+")
        self.normalize_regex2 = re.compile(r"[^a-z0-9 ]+")
        self.conversation_state = {"pending_question": None}

    async def run(self) -> None:
        while True:
            message = await self.websocket.receive()

            if message.get("type") == "websocket.disconnect":
                raise WebSocketDisconnect()

            if text := message.get("text"):
                await self.handle_text_message(text)

            if data := message.get("bytes"):
                # Parse channel from first byte
                # data format: [channel_byte][audio_data...]
                if len(data) > 1:
                    channel_byte = data[0]
                    channel = "customer" if channel_byte == 0 else "agent"
                    audio_data = data[1:]
                else:
                    channel = "customer"
                    audio_data = data

                deepgram = self.deepgrams.get(channel)
                if deepgram:
                    await deepgram.send_audio(bytes(audio_data))

    async def handle_text_message(self, raw_message: str) -> None:
        data = json.loads(raw_message)
        message_type = data.get("type")

        if message_type == "start_session":
            config = data.get("config", {})
            params = dict(config.get("deepgramParams") or {})
            params.setdefault("interim_results", "true")
            # Enable multichannel if not already set
            params.setdefault("multichannel", "true")
            self.gemini_model_override = config.get("geminiModel")

            # Create deepgram clients for each channel
            channels = config.get("channels", ["customer", "agent"])
            for ch in channels:
                dg = DeepgramClient(params)
                await dg.connect()
                self.deepgrams[ch] = dg
                self.deepgram_tasks[ch] = asyncio.create_task(self.read_deepgram(ch))

            await self.send_json(
                {"type": "session_started", "sessionId": self.session_id}
            )
            return

        if message_type == "stop_session":
            await self.close()

    async def read_deepgram(self, channel: str) -> None:
        deepgram = self.deepgrams.get(channel)
        if not deepgram:
            return
        try:
            while True:
                raw_message = await deepgram.recv()
                data = json.loads(raw_message)
                # Add channel info to the data
                data["channel_id"] = channel
                await self.handle_deepgram_message(data)
        except Exception as exc:
            if not self.closed:
                logger.exception(f"deepgram read failed for channel {channel}")
                await self.send_model(
                    ErrorEvent(
                        source="Deepgram",
                        message=str(exc),
                    )
                )

    async def handle_deepgram_message(self, data: dict) -> None:
        alternative = self._extract_primary_alternative(data)
        transcript = alternative.get("transcript", "")
        is_final = data.get("is_final", False)

        # Get channel_id from data (set in read_deepgram)
        channel_id = data.get("channel_id", "customer")

        # Map channel to speaker
        speaker_map = {"customer": "0", "agent": "1", "0": "0", "1": "1"}
        speaker = speaker_map.get(channel_id, "0")

        metadata = {
            "confidence": alternative.get("confidence"),
            "speech_final": data.get("speech_final", False),
            "channel": channel_id,
        }

        if transcript:
            self._cancel_finalize_task()
            await self.send_model(
                TranscriptEvent(
                    transcript=transcript,
                    isFinal=is_final,
                    metadata=metadata,
                    speaker=speaker,
                )
            )

            logger.info(
                f"Transcript: is_final={is_final}, speaker={speaker}, text={transcript[:50]}"
            )

            if is_final and transcript.strip():
                confidence = metadata["confidence"]
                logger.info(f"Capturing segment: confidence={confidence}")
                if self.should_capture_final_segment(transcript.strip(), confidence):
                    self.state.current_segments.append((transcript.strip(), speaker))
                    self.current_segment_confidences.append(
                        self.normalize_confidence(confidence)
                    )
                    self.finalized_segments = True
                    self._schedule_finalize()

            if metadata["speech_final"]:
                self._schedule_finalize()

        if data.get("type") == "UtteranceEnd":
            await self.send_json({"type": "utterance_end"})
            self._schedule_finalize()

    def _extract_primary_alternative(self, data: dict) -> dict:
        channel = data.get("channel", {})

        if isinstance(channel, list):
            channel = channel[0] if channel else {}

        if not isinstance(channel, dict):
            logger.warning(
                "Unexpected Deepgram channel payload type: %s", type(channel).__name__
            )
            return {}

        alternatives = channel.get("alternatives", [])
        if not isinstance(alternatives, list):
            logger.warning(
                "Unexpected Deepgram alternatives payload type: %s",
                type(alternatives).__name__,
            )
            return {}

        primary = alternatives[0] if alternatives else {}
        if not isinstance(primary, dict):
            logger.warning(
                "Unexpected Deepgram alternative item type: %s", type(primary).__name__
            )
            return {}

        return primary

    async def finalize_utterance(self) -> None:
        logger.info(
            f"finalize_utterance: finalized_segments={self.finalized_segments}, current_segments={len(self.state.current_segments)}"
        )
        if not self.finalized_segments or not self.state.current_segments:
            return

        text = " ".join(seg[0] for seg in self.state.current_segments).strip()
        speaker = (
            self.state.current_segments[0][1] if self.state.current_segments else None
        )
        self.state.current_segments = []
        self.finalized_segments = False
        average_confidence = self.get_average_confidence()
        self.current_segment_confidences = []

        if not text:
            return

        if self.pending_incomplete_utterance:
            text = f"{self.pending_incomplete_utterance} {text}".strip()
            self.pending_incomplete_utterance = ""

        # Bypass incomplete check for now - process all speech
        # if self.is_incomplete_utterance(text):
        #     self.pending_incomplete_utterance = text
        #     return
        pass  # Process immediately

        utterance_id = f"utt-{uuid.uuid4().hex[:12]}"
        # Update speaker-specific last utterances and history
        if speaker == "0":
            self.state.customer_last_utterance = text
            self.state.customer_history.append(text)
            if len(self.state.customer_history) > 20:
                self.state.customer_history.pop(0)
        elif speaker == "1":
            self.state.agent_last_utterance = text
            self.state.agent_history.append(text)
            if len(self.state.agent_history) > 20:
                self.state.agent_history.pop(0)
        self.state.messages.append(
            ConversationMessage(
                type="user", text=text, utterance_id=utterance_id, speaker=speaker
            )
        )
        if len(self.state.messages) > 1000:
            self.state.messages.pop(0)
        await self.send_model(
            UtteranceCommittedEvent(
                utteranceId=utterance_id,
                text=text,
            )
        )

        if self.should_extract_schema_fields(text, average_confidence):
            await self.extract_and_store_schema_fields(text)

        logger.info(f"ABOUT TO CHECK TRIGGER for: {text[:30]}")

        # Update call stage
        new_stage = self.detect_call_stage(text, speaker)
        if new_stage != self.state.call_stage:
            self.state.call_stage = new_stage

        # Update rolling summary
        await self.update_rolling_summary(text, speaker)

        # Check schema extraction for customer
        if speaker == "0":
            if self.conversation_state["pending_question"]:
                parsed = await self.gemini.parse_response(
                    text, self.conversation_state["pending_question"]
                )
                for k, v in parsed.items():
                    self.state.extracted_fields[k] = v
                self.conversation_state["pending_question"] = None
            missing = [
                f
                for f in ["loan_amount", "cibil_score"]
                if f not in self.state.extracted_fields
            ]
            if missing:
                question = await self.gemini.generate_question(
                    missing, self.build_recent_conversation_context()
                )
                self.conversation_state["pending_question"] = question

        # Smart trigger - invoke for any meaningful speech
        should_trigger = self.should_invoke_llm(text, average_confidence, speaker)
        logger.info(
            f"LLM trigger check: text={text[:30]}, confidence={average_confidence}, speaker={speaker}, triggered={should_trigger}"
        )
        if should_trigger:
            self.last_llm_invoked_at = time.monotonic()
            asyncio.create_task(self.generate_ai_response(text, utterance_id))

    def should_invoke_llm(
        self, utterance: str, average_confidence: float, speaker: str | None = None
    ) -> bool:
        # Simpler: just trigger on any real speech
        # Remove all complex checks for debugging
        if not utterance or len(utterance.strip()) < 2:
            return False

        # No cooldown for testing - always trigger
        # (can add back after confirmed working)
        # now = time.monotonic()
        # if now - self.last_llm_invoked_at < self.min_llm_interval_seconds:
        #     return False

        # Basic quality: skip empty/noise
        normalized = self._normalize_text(utterance)
        if not normalized or len(normalized) < 2:
            return False

        # Always trigger for testing - let LLM filter relevance
        logger.info(
            f"TRIGGER: utterance={utterance[:50]}, confidence={average_confidence}"
        )
        return True

    def _is_duplicate_utterance(self, normalized: str) -> bool:
        """Check if this is same as last user message"""
        for msg in reversed(self.state.messages):
            if msg.type == "user":
                last_msg = msg.text
                return bool(last_msg and self._normalize_text(last_msg) == normalized)
        return False

    def should_extract_schema_fields(
        self, utterance: str, average_confidence: float
    ) -> bool:
        normalized = self._normalize_text(utterance)
        if not normalized or average_confidence < 0.6:
            return False
        return len(normalized.split()) >= 4 or any(char.isdigit() for char in utterance)

    def should_capture_final_segment(
        self, transcript: str, confidence: float | None
    ) -> bool:
        normalized = self._normalize_text(transcript)
        if not normalized:
            return False
        if len(normalized) <= 2:
            return False
        if self.looks_like_noise_or_filler(normalized):
            return False
        if confidence is not None and self.normalize_confidence(confidence) < 0.45:
            return False
        return True

    def looks_like_noise_or_filler(self, normalized: str) -> bool:
        filler_only = {
            "hmm",
            "hmmm",
            "uh",
            "umm",
            "um",
            "ji",
            "haan",
            "han",
            "hello",
            "helo",
            "hi",
            "ok",
            "okay",
            "acha",
            "achha",
            "accha",
            "bolo",
            "boliye",
        }
        tokens = normalized.split()
        if not tokens:
            return True
        if normalized in filler_only:
            return True
        unique_tokens = set(tokens)
        if len(tokens) >= 4 and len(unique_tokens) == 1:
            return True
        return False

    def normalize_confidence(self, confidence: float | None) -> float:
        if confidence is None:
            return 0.75
        return max(0.0, min(float(confidence), 1.0))

    def get_average_confidence(self) -> float:
        if not self.current_segment_confidences:
            return 0.75
        return sum(self.current_segment_confidences) / len(
            self.current_segment_confidences
        )

    def is_incomplete_utterance(self, utterance: str) -> bool:
        normalized = self._normalize_text(utterance)
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

    async def _debounced_finalize(self) -> None:
        try:
            await asyncio.sleep(self.finalize_delay_seconds)
            await self.finalize_utterance()
        except asyncio.CancelledError:
            return

    def _schedule_finalize(self) -> None:
        self._cancel_finalize_task()
        self.finalize_task = asyncio.create_task(self._debounced_finalize())

    def _cancel_finalize_task(self) -> None:
        if self.finalize_task is not None and not self.finalize_task.done():
            self.finalize_task.cancel()
        self.finalize_task = None

    def _normalize_text(self, text: str) -> str:
        normalized = self.normalize_regex1.sub(" ", text.lower()).strip()
        normalized = self.normalize_regex2.sub("", normalized)
        return normalized.strip()

    def build_recent_conversation_context(self, limit: int = 8) -> str:
        recent_messages = self.state.messages[-limit:]
        lines: list[str] = []

        known_fields_text = self.build_known_fields_text(limit=12)
        if known_fields_text:
            lines.append(f"Known customer fields: {known_fields_text}")

        for msg in recent_messages:
            role = "Customer" if msg.type == "user" else "Caller Assist"
            if msg.speaker:
                if msg.speaker == "0":
                    role = "Customer"
                elif msg.speaker == "1":
                    role = "Agent"
            lines.append(f"{role}: {msg.text}")
        return "\n".join(lines) if lines else "No prior conversation context available."

    def build_known_fields_text(self, limit: int = 8) -> str:
        items = list(self.state.extracted_fields.items())
        if not items:
            return ""
        return ", ".join(f"{key}: {value}" for key, value in items[:limit])

    async def extract_and_store_schema_fields(self, utterance: str) -> None:
        conversation_context = self.build_recent_conversation_context()
        try:
            extracted = await self.gemini.extract_schema_values(
                utterance=utterance,
                conversation_context=conversation_context,
                known_fields=self.state.extracted_fields,
                schema_prompt=self.schema_registry.format_for_prompt(),
            )
        except Exception as exc:
            logger.warning("schema extraction failed: %s", exc)
            return

        for key, value in extracted.items():
            if key in self.schema_registry.fields:
                self.state.extracted_fields[key] = value

    async def generate_ai_response(self, utterance: str, utterance_id: str) -> None:
        logger.info(f"generate_ai_response CALLED for: {utterance[:50]}")
        async with self.ai_lock:
            if self.conversation_state["pending_question"]:
                question = self.conversation_state["pending_question"]
                self.conversation_state["pending_question"] = None
                full_text = f"[SUGGESTION] Ask: {question}"
                await self.send_model(
                    AIChunkEvent(
                        utteranceId=utterance_id,
                        text=full_text,
                    )
                )
                self.state.messages.append(
                    ConversationMessage(
                        type="ai",
                        text=full_text,
                        utterance_id=utterance_id,
                        badge_type="suggestion",
                    )
                )
                await self.send_model(
                    AIDoneEvent(
                        utteranceId=utterance_id,
                        fullText=full_text,
                        badgeType="suggestion",
                    )
                )
                return

            full_text = ""
            conversation_context = self.build_recent_conversation_context()

            logger.info(
                f"Calling Gemini with: utterance={utterance[:50]}, context={conversation_context[:100]}"
            )

            try:
                async for chunk in self.gemini.stream_reply(
                    utterance,
                    conversation_context,
                    self.gemini_model_override,
                    customer_last_utterance=self.state.customer_last_utterance,
                    agent_last_utterance=self.state.agent_last_utterance,
                    context_summary=conversation_context,
                    known_entities=self.state.extracted_fields,
                ):
                    full_text += chunk
                    await self.send_model(
                        AIChunkEvent(
                            utteranceId=utterance_id,
                            text=chunk,
                        )
                    )
                    await asyncio.sleep(0.01)
            except Exception as exc:
                logger.error(f"Gemini error: {exc}")
                await self.send_model(
                    ErrorEvent(
                        source="Gemini",
                        message=str(exc),
                    )
                )
                return

            full_text = self.normalize_ai_response(full_text, utterance)
            self.state.messages.append(
                ConversationMessage(
                    type="ai",
                    text=full_text,
                    utterance_id=utterance_id,
                    badge_type="suggestion",
                )
            )
            await self.send_model(
                AIDoneEvent(
                    utteranceId=utterance_id,
                    fullText=full_text,
                    badgeType="suggestion",
                )
            )

    def normalize_ai_response(self, raw_text: str, utterance: str) -> str:
        text = re.sub(r"\s+", " ", raw_text).strip()

        summary_match = re.search(
            r"\[SUMMARY\](.*?)(?=\[SUGGESTION\]|$)", text, re.IGNORECASE
        )
        suggestion_match = re.search(r"\[SUGGESTION\](.*)$", text, re.IGNORECASE)

        summary = summary_match.group(1).strip() if summary_match else ""
        suggestion = suggestion_match.group(1).strip() if suggestion_match else ""

        summary = re.sub(
            r"\[/?SUMMARY\]|\[/?SUGGESTION\]", "", summary, flags=re.IGNORECASE
        ).strip()
        suggestion = re.sub(
            r"\[/?SUMMARY\]|\[/?SUGGESTION\]", "", suggestion, flags=re.IGNORECASE
        ).strip()

        if summary and summary.lower().startswith("context:"):
            summary = summary[8:].strip()
        if summary and summary.lower().startswith("topic:"):
            summary = summary[6:].strip()
        if suggestion and suggestion.lower().startswith("suggestion:"):
            suggestion = suggestion[11:].strip()
        if suggestion and suggestion.lower().startswith("topic:"):
            suggestion = suggestion[6:].strip()

        if summary and suggestion and summary in suggestion:
            suggestion = suggestion.replace(summary, "", 1).strip(" .:-")

        if not summary:
            summary = self.build_fallback_summary(utterance)
        if not suggestion:
            suggestion = "Sir/ma'am, main aapki current concern ko clear karke next step confirm kar deta hoon."

        suggestion = re.sub(r"[\u0900-\u097F]+", "", suggestion).strip()
        summary = re.sub(r"[\u0900-\u097F]+", "", summary).strip()
        summary = self.convert_summary_to_hinglish(summary)
        customer_info = self.build_known_fields_text(limit=6)

        response = f"[SUMMARY] {summary}\n"
        if customer_info:
            response += f"[CUSTOMER_INFO] {customer_info}\n"
        response += f"[SUGGESTION] {suggestion}"
        return response

    def build_fallback_summary(self, utterance: str) -> str:
        cleaned = re.sub(r"\s+", " ", utterance).strip()
        if len(cleaned) > 120:
            cleaned = f"{cleaned[:117].rstrip()}..."
        return cleaned or "Current customer discussion"

    def detect_call_stage(self, utterance: str, speaker: str | None) -> str:
        normalized = self._normalize_text(utterance)
        tokens = set(normalized.split())

        discovery_keywords = {
            "ki",
            "kya",
            "kaise",
            "konsa",
            "kaun",
            "kitna",
            "inform",
            "about",
            "query",
            "pooch",
            "pucha",
        }
        negotiation_keywords = {
            "rate",
            "roi",
            "interest",
            "fee",
            "charges",
            "waive",
            "discount",
            "reduce",
            "lower",
            " EMI",
            " installment",
        }
        closing_keywords = {
            "okay",
            "thik",
            "achha",
            "good",
            "fine",
            "process",
            "apply",
            "submit",
            "documents",
            "disburse",
            "sanction",
            "approval",
        }

        has_discovery = bool(tokens & discovery_keywords)
        has_negotiation = bool(tokens & negotiation_keywords)
        has_closing = bool(tokens & closing_keywords)

        if has_closing and self.state.extracted_fields.get("loan_amount"):
            return "closing"
        if has_negotiation:
            return "negotiation"
        if has_discovery or not self.state.extracted_fields:
            return "discovery"
        return self.state.call_stage

    async def update_rolling_summary(self, utterance: str, speaker: str | None) -> None:
        if not utterance or len(utterance) < 20:
            return
        prompt = f"""Summarize this call segment in 1 short line: {utterance[:200]}"""
        try:
            summary = await self.gemini.generate_summary(prompt)
            new_summary = summary.get("summary", "")
            if new_summary:
                if self.state.rolling_summary:
                    self.state.rolling_summary = (
                        f"{self.state.rolling_summary} | {new_summary}"
                    )
                else:
                    self.state.rolling_summary = new_summary
                if len(self.state.rolling_summary) > 500:
                    self.state.rolling_summary = self.state.rolling_summary[-400:]
        except Exception:
            pass

    def convert_summary_to_hinglish(self, summary: str) -> str:
        lowered = summary.lower()
        replacements = [
            ("customer is concerned about", "customer ko concern hai about"),
            ("customer confirms", "customer confirm kar raha hai"),
            ("customer is asking about", "customer pooch raha hai about"),
            ("customer is discussing", "customer discuss kar raha hai"),
            ("customer wants", "customer chah raha hai"),
            ("customer requested", "customer ne request ki hai"),
            ("customer mentioned", "customer ne mention kiya hai"),
            ("loan sanction", "loan sanction"),
            ("upfront fee", "upfront fee"),
            ("property paper check", "property paper check"),
            ("property papers", "property papers"),
            ("rate of interest", "rate of interest"),
            ("fee waiver", "fee waiver"),
            ("current status", "current status"),
            ("next action", "next action"),
            ("and is concerned about", "aur concern hai about"),
            ("and wants", "aur chah raha hai"),
        ]

        updated = summary
        for source, target in replacements:
            updated = re.sub(source, target, updated, flags=re.IGNORECASE)

        if updated == summary:
            updated = re.sub(
                r"^\s*customer\s+", "", updated, flags=re.IGNORECASE
            ).strip()
            updated = re.sub(r"^\s*customer\b", "", updated, flags=re.IGNORECASE).strip(
                " :-"
            )

        return updated

    async def generate_summary(self) -> dict:
        return {
            "customer_info": dict(self.state.extracted_fields),
        }

    async def send_model(self, model) -> None:
        await self.send_json(model.model_dump())

    async def send_json(self, payload: dict) -> None:
        if self.closed or self.connection_closed:
            return
        await self.websocket.send_json(payload)

    async def close(self) -> None:
        self.closed = True
        self.connection_closed = True
        self._cancel_finalize_task()

        # Close all deepgram connections
        for channel, deepgram in self.deepgrams.items():
            try:
                await deepgram.send_close()
            except Exception:
                pass
            await deepgram.close()
        self.deepgrams.clear()

        # Cancel all deepgram tasks
        for task in self.deepgram_tasks.values():
            if task:
                task.cancel()
        self.deepgram_tasks.clear()


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, SessionRuntime] = {}

    async def create_session(self, websocket: WebSocket) -> SessionRuntime:
        session = SessionRuntime(websocket)
        self._sessions[session.session_id] = session
        return session

    def get_session(self, session_id: str) -> SessionRuntime | None:
        return self._sessions.get(session_id)

    async def close_session(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session is not None:
            await session.close()
