import asyncio
import json
import logging
import time

from fastapi import WebSocketDisconnect

from app.models.events import ErrorEvent
from app.models.events import TranscriptEvent
from app.services.field_resolver import build_resolved_field_state
from app.services.lead_detail_context import build_priority_missing_fields
from app.services.sarvam_client import SarvamClient
from app.services.sarvam_client import build_sarvam_params
from app.services.session_text import normalize_confidence

logger = logging.getLogger(__name__)

ASR_AUDIO_QUEUE_FRAMES = 120
AUDIO_DIAGNOSTIC_INTERVAL_SECONDS = 5.0


def should_send_transcript_update(
    transcript: str,
    *,
    is_final: bool,
    speaker: str,
    confidence: float | None,
) -> bool:
    return bool(str(transcript or "").strip())


async def run(session) -> None:
    while True:
        message = await session.websocket.receive()

        if message.get("type") == "websocket.disconnect":
            raise WebSocketDisconnect()

        if text := message.get("text"):
            await handle_text_message(session, text)

        if data := message.get("bytes"):
            if len(data) > 1:
                channel_byte = data[0]
                channel = "customer" if channel_byte == 0 else "agent"
                audio_data = data[1:]
            else:
                channel = "customer"
                audio_data = data

            send_queue = session.transcription_send_queues.get(channel)
            if send_queue is not None:
                audio_frame = bytes(audio_data)
                _log_audio_received(session, channel, audio_frame, send_queue.qsize())
                try:
                    send_queue.put_nowait(audio_frame)
                except asyncio.QueueFull:
                    try:
                        send_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                    send_queue.put_nowait(audio_frame)
                    logger.warning("Dropped stale ASR audio frame for congested channel %s", channel)


def update_lead_context(session, data: dict) -> None:
    lead_id = data.get("lead_id") or data.get("leadId")
    lead_facts = data.get("lead_facts") or data.get("leadFacts") or {}
    lead_detail = data.get("lead_detail") or data.get("leadDetail") or lead_facts
    lead_missing_fields = data.get("lead_missing_fields") or data.get("leadMissingFields") or []

    if lead_id is not None:
        session.state.lead_id = str(lead_id)
    session.state.lead_detail = lead_detail if isinstance(lead_detail, dict) else {}
    session.state.lead_facts = lead_facts if isinstance(lead_facts, dict) else {}
    session.state.lead_missing_fields = lead_missing_fields if isinstance(lead_missing_fields, list) else []
    session.state.lead_priority_missing_fields = build_priority_missing_fields(
        lead_detail if isinstance(lead_detail, dict) else {},
        session.state.lead_missing_fields,
    )
    session.state.resolved_field_state = build_resolved_field_state(
        existing=session.state.resolved_field_state,
        lead_detail=session.state.lead_detail,
        lead_facts=session.state.lead_facts,
        extracted_fields=session.state.extracted_fields,
    )
    logger.info(
        "Session lead context updated: session_id=%s lead_id=%s missing=%d priority_missing=%d",
        session.session_id,
        session.state.lead_id,
        len(session.state.lead_missing_fields),
        len(session.state.lead_priority_missing_fields),
    )


async def handle_text_message(session, raw_message: str) -> None:
    try:
        data = json.loads(raw_message)
    except json.JSONDecodeError as exc:
        logger.warning("Received malformed text frame: %s", exc)
        await session.send_model(ErrorEvent(source="Transport", message=f"Invalid JSON: {exc}"))
        return
    message_type = data.get("type")

    if message_type == "start_session":
        config = data.get("config", {})
        params = build_sarvam_params(config)
        session.model_override = (
            config.get("modelOverride") or config.get("aiModel") or config.get("geminiModel")
        )
        if config.get("leadFacts") or config.get("leadMissingFields") or config.get("leadId"):
            update_lead_context(
                session,
                {
                    "leadId": config.get("leadId"),
                    "leadFacts": config.get("leadFacts"),
                    "leadMissingFields": config.get("leadMissingFields"),
                },
            )

        channels = config.get("channels", ["customer", "agent"])
        logger.info(
            "Starting ASR session: session_id=%s channels=%s params=%s",
            session.session_id,
            ",".join(channels),
            {
                key: value
                for key, value in params.items()
                if key not in {"api_key", "apiKey", "SARVAM_API_KEY"}
            },
        )
        for ch in channels:
            logger.info(
                "Starting ASR channel: session_id=%s channel=%s params=%s",
                session.session_id,
                ch,
                {
                    key: value
                    for key, value in params.items()
                    if key not in {"api_key", "apiKey", "SARVAM_API_KEY"}
                },
            )
            client = SarvamClient(params)
            await client.connect()
            session.transcription_clients[ch] = client
            session.transcription_send_queues[ch] = asyncio.Queue(maxsize=ASR_AUDIO_QUEUE_FRAMES)
            session.transcription_send_tasks[ch] = asyncio.create_task(send_transcription(session, ch))
            session.transcription_tasks[ch] = asyncio.create_task(read_transcription(session, ch))

        await session.send_json({"type": "session_started", "sessionId": session.session_id})
        logger.info("ASR session ready: session_id=%s channels=%s", session.session_id, ",".join(channels))
        return

    if message_type == "lead_context":
        update_lead_context(session, data)
        return

    if message_type == "stop_session":
        await close(session)


async def read_transcription(session, channel: str) -> None:
    transcriber = session.transcription_clients.get(channel)
    if not transcriber:
        return
    try:
        while True:
            raw_message = await transcriber.recv()
            data = asr_message_to_dict(raw_message)
            _log_empty_asr_data_frame(session, channel, data)
            data = normalize_sarvam_message(data)
            data["channel_id"] = channel
            await handle_transcription_message(session, data)
    except Exception as exc:
        if not session.closed:
            logger.exception("Sarvam transcription read failed for channel %s", channel)
            await session.send_model(ErrorEvent(source="Sarvam ASR", message=str(exc)))


async def send_transcription(session, channel: str) -> None:
    transcriber = session.transcription_clients.get(channel)
    send_queue = session.transcription_send_queues.get(channel)
    if not transcriber or send_queue is None:
        return
    try:
        while not session.closed and channel in session.transcription_clients:
            audio_data = await send_queue.get()
            try:
                if not await transcriber.send_audio(audio_data):
                    logger.warning("ASR channel %s closed while sending audio", channel)
                    session.transcription_clients.pop(channel, None)
                    task = session.transcription_tasks.pop(channel, None)
                    if task:
                        task.cancel()
                    break
                _log_audio_sent(session, channel, audio_data)
                await transcriber.flush_if_due()
            finally:
                send_queue.task_done()
    except asyncio.CancelledError:
        return
    except Exception as exc:
        if not session.closed:
            logger.exception("Sarvam transcription send failed for channel %s", channel)
            await session.send_model(ErrorEvent(source="Sarvam ASR", message=str(exc)))


async def handle_transcription_message(session, data: dict) -> None:
    event_type = data.get("type")
    channel_id = data.get("channel_id", "customer")
    if event_type in {
        "speech_start",
        "speech_end",
        "transcript",
    }:
        logger.info(
            "Sarvam transcription event: channel=%s type=%s snippet=%s",
            channel_id,
            event_type,
            str(
                data.get("text") or data.get("transcript") or ""
            )[:80],
        )
    if event_type == "error":
        error = data.get("error") if isinstance(data.get("error"), dict) else {}
        message = error.get("message") or data.get("message") or "Sarvam transcription error"
        await session.send_model(ErrorEvent(source="Sarvam ASR", message=str(message)))
        return

    transcript, is_final = extract_sarvam_transcript(data)
    if not transcript and event_type not in {"speech_start", "speech_end"}:
        return

    channel_id = data.get("channel_id", "customer")

    speaker_map = {"customer": "0", "agent": "1", "0": "0", "1": "1"}
    speaker = speaker_map.get(channel_id, "0")

    metadata = {
        "confidence": 0.75,
        "speech_final": event_type == "speech_end",
        "channel": channel_id,
        "provider": "sarvam",
    }

    if transcript:
        confidence = metadata["confidence"]
        if not should_send_transcript_update(
            transcript,
            is_final=is_final,
            speaker=speaker,
            confidence=confidence,
        ):
            return

        session._cancel_finalize_task()
        await session.send_model(
            TranscriptEvent(
                transcript=transcript,
                isFinal=is_final,
                metadata=metadata,
                speaker=speaker,
            )
        )

        if is_final and transcript.strip():
            if (
                session.state.current_segments
                and session.state.current_segments[0][1] != speaker
            ):
                session.finalized_segments = True
                session._cancel_finalize_task()
                await session.finalize_utterance()
            session.state.current_segments.append((transcript.strip(), speaker))
            session.current_segment_confidences.append(
                normalize_confidence(confidence)
            )
            session.finalized_segments = True
            session._schedule_finalize()

        if metadata["speech_final"] and session.state.current_segments:
            session._schedule_finalize()

    if event_type == "transcript" and session.state.current_segments:
        session._schedule_finalize()


def extract_sarvam_transcript(data: dict) -> tuple[str, bool]:
    transcript = _first_text(
        data,
        ("data", "transcript"),
        ("data", "text"),
        ("data", "translation"),
        ("transcript",),
        ("text",),
        ("translation",),
    )
    if transcript:
        return transcript, True
    return "", False


def normalize_sarvam_message(data: dict) -> dict:
    event_type = data.get("type")
    payload = data.get("data") if isinstance(data.get("data"), dict) else {}

    transcript, _ = extract_sarvam_transcript(data)
    if transcript:
        return {
            "type": "transcript",
            "text": transcript,
            "request_id": payload.get("request_id") or data.get("request_id"),
            "language_code": payload.get("language_code") or data.get("language_code"),
        }

    if event_type == "events":
        signal_type = str(payload.get("signal_type") or payload.get("event_type") or "")
        if signal_type == "START_SPEECH":
            return {"type": "speech_start", **payload}
        if signal_type == "END_SPEECH":
            return {"type": "speech_end", **payload}

    if event_type == "error":
        return {
            "type": "error",
            "message": payload.get("error") or data.get("message") or "Sarvam transcription error",
            "code": payload.get("code"),
        }

    return data


def asr_message_to_dict(raw_message) -> dict:
    if isinstance(raw_message, str):
        return json.loads(raw_message)
    if isinstance(raw_message, dict):
        return dict(raw_message)
    if hasattr(raw_message, "model_dump"):
        return raw_message.model_dump()
    if hasattr(raw_message, "dict"):
        return raw_message.dict()
    return dict(raw_message)


def _first_text(data: dict, *paths: tuple[str, ...]) -> str:
    for path in paths:
        value = data
        for key in path:
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(key)
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _log_audio_received(session, channel: str, audio_frame: bytes, queue_size: int) -> None:
    count = _increment_counter(session.audio_receive_counts, channel)
    if not _should_log_counter(session.last_audio_receive_log_at, channel, count):
        return
    logger.info(
        "Backend received audio frame: session_id=%s channel=%s frames=%d bytes=%d peak=%d queue=%d",
        session.session_id,
        channel,
        count,
        len(audio_frame),
        _pcm16_peak(audio_frame),
        queue_size,
    )


def _log_audio_sent(session, channel: str, audio_frame: bytes) -> None:
    count = _increment_counter(session.audio_send_counts, channel)
    if not _should_log_counter(session.last_audio_send_log_at, channel, count):
        return
    logger.info(
        "Sent audio frame to ASR: session_id=%s channel=%s frames=%d bytes=%d peak=%d",
        session.session_id,
        channel,
        count,
        len(audio_frame),
        _pcm16_peak(audio_frame),
    )


def _log_empty_asr_data_frame(session, channel: str, data: dict) -> None:
    if data.get("type") != "data":
        return
    if _first_text(data, ("data", "transcript"), ("data", "text"), ("data", "translation")):
        return
    payload = data.get("data") if isinstance(data.get("data"), dict) else {}
    count = _increment_counter(session.asr_empty_counts, channel)
    if not _should_log_counter(session.last_asr_empty_log_at, channel, count):
        return
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
    logger.info(
        "ASR returned empty transcript: session_id=%s channel=%s empty_frames=%d audio_duration=%s latency=%s request_id=%s",
        session.session_id,
        channel,
        count,
        metrics.get("audio_duration"),
        metrics.get("processing_latency"),
        payload.get("request_id"),
    )


def _increment_counter(counters: dict[str, int], channel: str) -> int:
    counters[channel] = counters.get(channel, 0) + 1
    return counters[channel]


def _should_log_counter(last_log_at: dict[str, float], channel: str, count: int) -> bool:
    now = time.monotonic()
    previous = last_log_at.get(channel, 0.0)
    if count == 1 or now - previous >= AUDIO_DIAGNOSTIC_INTERVAL_SECONDS:
        last_log_at[channel] = now
        return True
    return False


def _pcm16_peak(payload: bytes) -> int:
    limit = len(payload) - (len(payload) % 2)
    peak = 0
    for index in range(0, limit, 2):
        sample = int.from_bytes(payload[index : index + 2], "little", signed=True)
        peak = max(peak, abs(sample))
    return peak


async def close(session) -> None:
    session.closed = True
    session.connection_closed = True
    session._cancel_finalize_task()

    for task in session.transcription_send_tasks.values():
        if task:
            task.cancel()
    session.transcription_send_tasks.clear()
    session.transcription_send_queues.clear()

    for channel, transcriber in list(session.transcription_clients.items()):
        try:
            await transcriber.send_close()
        except Exception:
            pass
        await transcriber.close()
    session.transcription_clients.clear()

    for task in session.transcription_tasks.values():
        if task:
            task.cancel()
    session.transcription_tasks.clear()
