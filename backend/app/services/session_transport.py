import asyncio
import json
import logging

from fastapi import WebSocketDisconnect

from app.models.events import ErrorEvent
from app.models.events import TranscriptEvent
from app.services.deepgram_client import DeepgramClient
from app.services.session_text import (
    normalize_confidence,
    should_capture_final_segment,
)

logger = logging.getLogger(__name__)


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

            deepgram = session.deepgrams.get(channel)
            if deepgram and not await deepgram.send_audio(bytes(audio_data)):
                logger.warning("Deepgram channel %s closed while sending audio", channel)
                session.deepgrams.pop(channel, None)
                task = session.deepgram_tasks.pop(channel, None)
                if task:
                    task.cancel()
                keepalive_task = session.deepgram_keepalive_tasks.pop(channel, None)
                if keepalive_task:
                    keepalive_task.cancel()


async def handle_text_message(session, raw_message: str) -> None:
    data = json.loads(raw_message)
    message_type = data.get("type")

    if message_type == "start_session":
        config = data.get("config", {})
        params = dict(config.get("deepgramParams") or {})
        params.setdefault("interim_results", "true")
        params.setdefault("multichannel", "true")
        session.model_override = (
            config.get("modelOverride") or config.get("aiModel") or config.get("geminiModel")
        )

        channels = config.get("channels", ["customer", "agent"])
        for ch in channels:
            dg = DeepgramClient(params)
            await dg.connect()
            session.deepgrams[ch] = dg
            session.deepgram_tasks[ch] = asyncio.create_task(read_deepgram(session, ch))
            session.deepgram_keepalive_tasks[ch] = asyncio.create_task(
                keepalive_deepgram(session, ch)
            )

        await session.send_json({"type": "session_started", "sessionId": session.session_id})
        return

    if message_type == "stop_session":
        await close(session)


async def read_deepgram(session, channel: str) -> None:
    deepgram = session.deepgrams.get(channel)
    if not deepgram:
        return
    try:
        while True:
            raw_message = await deepgram.recv()
            data = json.loads(raw_message)
            data["channel_id"] = channel
            await handle_deepgram_message(session, data)
    except Exception as exc:
        if not session.closed:
            logger.exception("deepgram read failed for channel %s", channel)
            await session.send_model(ErrorEvent(source="Deepgram", message=str(exc)))


async def keepalive_deepgram(session, channel: str) -> None:
    deepgram = session.deepgrams.get(channel)
    if not deepgram:
        return
    try:
        while not session.closed and channel in session.deepgrams:
            await asyncio.sleep(5)
            if not await deepgram.send_keepalive():
                logger.info("Stopping Deepgram keepalive for closed channel %s", channel)
                break
    except asyncio.CancelledError:
        return
    except Exception as exc:
        if not session.closed:
            logger.warning("Deepgram keepalive failed for channel %s: %s", channel, exc)


async def handle_deepgram_message(session, data: dict) -> None:
    alternative = extract_primary_alternative(data)
    transcript = alternative.get("transcript", "")
    is_final = data.get("is_final", False)
    channel_id = data.get("channel_id", "customer")

    speaker_map = {"customer": "0", "agent": "1", "0": "0", "1": "1"}
    speaker = speaker_map.get(channel_id, "0")

    metadata = {
        "confidence": alternative.get("confidence"),
        "speech_final": data.get("speech_final", False),
        "channel": channel_id,
    }

    if transcript:
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
            confidence = metadata["confidence"]
            if should_capture_final_segment(transcript.strip(), confidence):
                session.state.current_segments.append((transcript.strip(), speaker))
                session.current_segment_confidences.append(
                    normalize_confidence(confidence)
                )
                session.finalized_segments = True
                session._schedule_finalize()

        if metadata["speech_final"]:
            session._schedule_finalize()

    if data.get("type") == "UtteranceEnd":
        await session.send_json({"type": "utterance_end"})
        session._schedule_finalize()


def extract_primary_alternative(data: dict) -> dict:
    alternatives = data.get("alternatives", [])
    if isinstance(alternatives, list) and alternatives:
        primary = alternatives[0]
        if isinstance(primary, dict):
            return primary

    channel = data.get("channel", {})
    if isinstance(channel, list):
        channel = channel[0] if channel else {}
    if not isinstance(channel, dict):
        if isinstance(channel, int):
            logger.debug("Deepgram channel index payload: %s", channel)
        else:
            logger.warning("Unexpected Deepgram channel payload type: %s", type(channel).__name__)
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


async def close(session) -> None:
    session.closed = True
    session.connection_closed = True
    session._cancel_finalize_task()

    for channel, deepgram in session.deepgrams.items():
        try:
            await deepgram.send_close()
        except Exception:
            pass
        await deepgram.close()
    session.deepgrams.clear()

    for task in session.deepgram_tasks.values():
        if task:
            task.cancel()
    session.deepgram_tasks.clear()

    for task in session.deepgram_keepalive_tasks.values():
        if task:
            task.cancel()
    session.deepgram_keepalive_tasks.clear()
