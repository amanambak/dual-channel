import base64
import json
import socket

import websockets
from websockets.asyncio.client import ClientConnection
from websockets.exceptions import ConnectionClosed

from app.core.config import get_settings


AGENT_TRANSCRIPTION_PROMPT = (
    "Transcribe only the words clearly spoken in the audio. "
    "For Hindi or Hinglish speech, use natural Roman-script Hinglish. "
    "Do not translate, paraphrase, correct, infer names, complete sentences, "
    "or add any words that were not spoken. If audio is unclear, omit unclear words."
)


class OpenAIRealtimeTranscriptionClient:
    def __init__(self, params: dict | None = None, channel: str = "customer") -> None:
        self.settings = get_settings()
        self.params = params or {}
        self.channel = channel
        self.connection: ClientConnection | None = None

    async def connect(self) -> ClientConnection:
        self.connection = await websockets.connect(
            self.settings.openai_realtime_ws_url,
            additional_headers={"Authorization": f"Bearer {self.settings.openai_api_key}"},
            max_size=2**24,
            compression=None,
        )
        self._enable_tcp_nodelay()
        await self._configure_session()
        return self.connection

    def _enable_tcp_nodelay(self) -> None:
        if self.connection is None:
            return
        transport = getattr(self.connection, "transport", None)
        if transport is None:
            return
        sock = transport.get_extra_info("socket")
        if sock is None:
            return
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            return

    async def _configure_session(self) -> None:
        if self.connection is None:
            return

        transcription: dict[str, str] = {
            "model": str(
                self.params.get("model")
                or self.settings.openai_transcription_model
            )
        }
        prompt = self._resolve_transcription_prompt()
        language = self.params.get("language") or self.settings.openai_transcription_language
        if prompt:
            transcription["prompt"] = str(prompt)
        if language and language != "multi":
            transcription["language"] = str(language)

        await self.connection.send(
            json.dumps(
                {
                    "type": "session.update",
                    "session": {
                        "type": "transcription",
                        "audio": {
                            "input": {
                                "format": {"type": "audio/pcm", "rate": 24000},
                                "transcription": transcription,
                                "turn_detection": _build_turn_detection(self.params),
                                **_noise_reduction_config(self.params, self.channel),
                            }
                        },
                        "include": ["item.input_audio_transcription.logprobs"],
                    },
                }
            )
        )

    def _resolve_transcription_prompt(self) -> str:
        if self.channel == "agent":
            return str(
                self.params.get("agent_prompt")
                or self.params.get("agentPrompt")
                or AGENT_TRANSCRIPTION_PROMPT
            )
        return str(
            self.params.get("customer_prompt")
            or self.params.get("customerPrompt")
            or self.params.get("prompt")
            or self.settings.openai_transcription_prompt
            or ""
        )

    async def send_audio(self, payload: bytes) -> bool:
        if self.connection is None:
            return False
        try:
            await self.connection.send(
                json.dumps(
                    {
                        "type": "input_audio_buffer.append",
                        "audio": base64.b64encode(payload).decode("ascii"),
                    }
                )
            )
            return True
        except ConnectionClosed:
            return False

    async def send_keepalive(self) -> bool:
        if self.connection is None:
            return False
        try:
            await self.connection.ping()
            return True
        except ConnectionClosed:
            return False

    async def send_close(self) -> None:
        if self.connection is None:
            return
        await self.connection.send(json.dumps({"type": "session.close"}))

    async def recv(self) -> str:
        if self.connection is None:
            raise RuntimeError("OpenAI Realtime transcription connection is not open")
        return await self.connection.recv()

    async def close(self) -> None:
        if self.connection is not None:
            await self.connection.close()
            self.connection = None


def _int_param(params: dict, key: str, default: int) -> int:
    try:
        return int(params.get(key, default))
    except (TypeError, ValueError):
        return default


def _float_param(params: dict, key: str, default: float) -> float:
    try:
        return float(params.get(key, default))
    except (TypeError, ValueError):
        return default


def _build_turn_detection(params: dict) -> dict:
    vad_type = str(params.get("vad_type") or "server_vad")
    if vad_type == "semantic_vad":
        return {
            "type": "semantic_vad",
            "eagerness": str(params.get("vad_eagerness") or "low"),
            "create_response": False,
            "interrupt_response": False,
        }
    return {
        "type": "server_vad",
        "threshold": _float_param(params, "vad_threshold", 0.45),
        "prefix_padding_ms": _int_param(params, "prefix_padding_ms", 800),
        "silence_duration_ms": _int_param(params, "silence_duration_ms", 700),
        "create_response": False,
        "interrupt_response": False,
    }


def _noise_reduction_config(params: dict, channel: str) -> dict:
    noise_reduction = _resolve_noise_reduction(params, channel)
    if noise_reduction in {"", "none", "off", "false", "disabled"}:
        return {}
    return {"noise_reduction": {"type": noise_reduction}}


def _resolve_noise_reduction(params: dict, channel: str) -> str:
    explicit = params.get("noise_reduction")
    if explicit is not None:
        return str(explicit).strip().lower()
    if channel == "customer":
        return "none"
    return "none"
