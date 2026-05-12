import asyncio
import json
import logging

from fastapi import WebSocketDisconnect

from app.models.events import ErrorEvent
from app.models.events import TranscriptEvent
from app.services.field_resolver import build_resolved_field_state
from app.services.lead_detail_context import build_priority_missing_fields
from app.services.openai_realtime_client import OpenAIRealtimeTranscriptionClient
from app.services.session_text import normalize_confidence

logger = logging.getLogger(__name__)

OPENAI_AUDIO_QUEUE_FRAMES = 240


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
                try:
                    send_queue.put_nowait(audio_frame)
                except asyncio.QueueFull:
                    try:
                        send_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                    send_queue.put_nowait(audio_frame)
                    logger.warning("Dropped stale OpenAI audio frame for congested channel %s", channel)


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
        params = dict(config.get("openaiTranscriptionParams") or {})
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
        for ch in channels:
            client = OpenAIRealtimeTranscriptionClient(params, channel=ch)
            await client.connect()
            session.transcription_clients[ch] = client
            session.transcription_send_queues[ch] = asyncio.Queue(maxsize=OPENAI_AUDIO_QUEUE_FRAMES)
            session.transcription_send_tasks[ch] = asyncio.create_task(send_transcription(session, ch))
            session.transcription_tasks[ch] = asyncio.create_task(read_transcription(session, ch))
            session.transcription_keepalive_tasks[ch] = asyncio.create_task(
                keepalive_transcription(session, ch)
            )

        await session.send_json({"type": "session_started", "sessionId": session.session_id})
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
            data = json.loads(raw_message)
            data["channel_id"] = channel
            await handle_transcription_message(session, data)
    except Exception as exc:
        if not session.closed:
            logger.exception("OpenAI transcription read failed for channel %s", channel)
            await session.send_model(ErrorEvent(source="OpenAI Realtime", message=str(exc)))


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
                    logger.warning("OpenAI transcription channel %s closed while sending audio", channel)
                    session.transcription_clients.pop(channel, None)
                    task = session.transcription_tasks.pop(channel, None)
                    if task:
                        task.cancel()
                    keepalive_task = session.transcription_keepalive_tasks.pop(channel, None)
                    if keepalive_task:
                        keepalive_task.cancel()
                    break
            finally:
                send_queue.task_done()
    except asyncio.CancelledError:
        return
    except Exception as exc:
        if not session.closed:
            logger.exception("OpenAI transcription send failed for channel %s", channel)
            await session.send_model(ErrorEvent(source="OpenAI Realtime", message=str(exc)))


async def keepalive_transcription(session, channel: str) -> None:
    transcriber = session.transcription_clients.get(channel)
    if not transcriber:
        return
    try:
        while not session.closed and channel in session.transcription_clients:
            await asyncio.sleep(5)
            if not await transcriber.send_keepalive():
                logger.info("Stopping OpenAI transcription keepalive for closed channel %s", channel)
                break
    except asyncio.CancelledError:
        return
    except Exception as exc:
        if not session.closed:
            logger.warning("OpenAI transcription keepalive failed for channel %s: %s", channel, exc)


async def handle_transcription_message(session, data: dict) -> None:
    event_type = data.get("type")
    channel_id = data.get("channel_id", "customer")
    if event_type in {
        "session.created",
        "session.updated",
        "input_audio_buffer.speech_started",
        "input_audio_buffer.speech_stopped",
        "conversation.item.input_audio_transcription.delta",
        "conversation.item.input_audio_transcription.completed",
    }:
        logger.info(
            "OpenAI transcription event: channel=%s type=%s item_id=%s snippet=%s",
            channel_id,
            event_type,
            data.get("item_id"),
            str(
                data.get("transcript")
                or data.get("text")
                or data.get("delta")
                or ""
            )[:80],
        )
    if event_type == "error":
        error = data.get("error") if isinstance(data.get("error"), dict) else {}
        message = error.get("message") or data.get("message") or "Realtime transcription error"
        await session.send_model(ErrorEvent(source="OpenAI Realtime", message=str(message)))
        return
    if event_type == "conversation.item.input_audio_transcription.segment":
        return

    transcript, is_final, item_id = extract_openai_transcript(session, data)
    if not transcript and event_type not in {
        "input_audio_buffer.speech_started",
        "input_audio_buffer.speech_stopped",
    }:
        return

    channel_id = data.get("channel_id", "customer")

    speaker_map = {"customer": "0", "agent": "1", "0": "0", "1": "1"}
    speaker = speaker_map.get(channel_id, "0")

    metadata = {
        "confidence": extract_logprob_confidence(data) if is_final else None,
        "speech_final": event_type == "input_audio_buffer.speech_stopped",
        "channel": channel_id,
        "item_id": item_id,
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

    if event_type == "conversation.item.input_audio_transcription.completed":
        if session.state.current_segments:
            session._schedule_finalize()


def extract_openai_transcript(session, data: dict) -> tuple[str, bool, str | None]:
    event_type = data.get("type")
    channel_id = str(data.get("channel_id", "customer"))
    item_id = data.get("item_id")
    item_key = str(item_id or data.get("event_id") or "")

    if event_type == "conversation.item.input_audio_transcription.delta":
        delta = str(data.get("delta") or "")
        if not delta:
            return "", False, item_id
        key = (channel_id, item_key)
        transcript = f"{session.transcript_delta_buffers.get(key, '')}{delta}"
        session.transcript_delta_buffers[key] = transcript
        return transcript, False, item_id

    if event_type == "conversation.item.input_audio_transcription.completed":
        transcript = str(data.get("transcript") or "")
        if item_key:
            session.transcript_delta_buffers.pop((channel_id, item_key), None)
        return transcript, True, item_id

    return "", False, item_id


def extract_logprob_confidence(data: dict) -> float | None:
    logprobs = data.get("logprobs")
    if not isinstance(logprobs, list) or not logprobs:
        return None
    probabilities = []
    for item in logprobs:
        if not isinstance(item, dict):
            continue
        logprob = item.get("logprob")
        if isinstance(logprob, (int, float)):
            probabilities.append(2.718281828459045 ** float(logprob))
    if not probabilities:
        return None
    return sum(probabilities) / len(probabilities)


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

    for task in session.transcription_keepalive_tasks.values():
        if task:
            task.cancel()
    session.transcription_keepalive_tasks.clear()
    session.transcript_delta_buffers.clear()
