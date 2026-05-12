import base64
import json
import time
from typing import Any
from urllib.parse import urlencode

import websockets

from app.core.config import get_settings


class SarvamClient:
    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self.settings = get_settings()
        self.params = params or {}
        self.websocket = None
        self.last_flush_at = 0.0

    def connection_config(self) -> tuple[str, dict[str, str]]:
        if not self.settings.sarvam_api_key:
            raise RuntimeError("SARVAM_API_KEY is required for Sarvam ASR")

        query = {
            "model": self.model,
            "mode": self.mode,
            "language-code": self.language_code,
            "sample_rate": str(self.sample_rate),
            "input_audio_codec": self.input_audio_codec,
            "high_vad_sensitivity": _bool_string(self.high_vad_sensitivity),
            "vad_signals": _bool_string(self.vad_signals),
            "flush_signal": _bool_string(self.flush_signal),
        }
        return (
            f"{self.settings.sarvam_ws_url}?{urlencode(query)}",
            {"Api-Subscription-Key": self.settings.sarvam_api_key},
        )

    async def connect(self) -> None:
        url, headers = self.connection_config()
        self.websocket = await websockets.connect(url, additional_headers=headers)

    @property
    def model(self) -> str:
        return str(self.params.get("model") or self.settings.sarvam_model)

    @property
    def mode(self) -> str:
        return str(self.params.get("mode") or self.settings.sarvam_mode)

    @property
    def language_code(self) -> str:
        return str(
            self.params.get("language_code")
            or self.params.get("languageCode")
            or self.params.get("language")
            or self.settings.sarvam_language_code
        )

    @property
    def sample_rate(self) -> int:
        return _int_param(
            self.params,
            "sample_rate",
            _int_param(self.params, "sampleRate", self.settings.sarvam_sample_rate),
        )

    @property
    def input_audio_codec(self) -> str:
        return str(
            self.params.get("input_audio_codec")
            or self.params.get("inputAudioCodec")
            or self.settings.sarvam_input_audio_codec
        )

    @property
    def encoding(self) -> str:
        return str(self.params.get("encoding") or self.settings.sarvam_encoding)

    @property
    def high_vad_sensitivity(self) -> bool:
        return _bool_param(
            self.params.get("high_vad_sensitivity", self.params.get("highVadSensitivity")),
            self.settings.sarvam_high_vad_sensitivity,
        )

    @property
    def vad_signals(self) -> bool:
        return _bool_param(
            self.params.get("vad_signals", self.params.get("vadSignals")),
            self.settings.sarvam_vad_signals,
        )

    @property
    def flush_signal(self) -> bool:
        return _bool_param(
            self.params.get("flush_signal", self.params.get("flushSignal")),
            self.settings.sarvam_flush_signal,
        )

    @property
    def flush_interval_seconds(self) -> float:
        interval_ms = _int_param(
            self.params,
            "flush_interval_ms",
            _int_param(self.params, "flushIntervalMs", self.settings.sarvam_flush_interval_ms),
        )
        return max(interval_ms, 0) / 1000

    async def send_audio(self, payload: bytes) -> bool:
        if self.websocket is None:
            return False
        message = {
            "audio": {
                "data": base64.b64encode(payload).decode("ascii"),
                "sample_rate": self.sample_rate,
                "encoding": self.encoding,
            }
        }
        await self.websocket.send(json.dumps(message))
        return True

    async def flush_if_due(self) -> None:
        if not self.flush_signal or self.websocket is None:
            return
        interval = self.flush_interval_seconds
        if interval <= 0:
            return
        now = time.monotonic()
        if now - self.last_flush_at < interval:
            return
        self.last_flush_at = now
        await self.websocket.send(json.dumps({"type": "flush"}))

    async def send_close(self) -> None:
        return None

    async def recv(self) -> dict:
        if self.websocket is None:
            raise RuntimeError("Sarvam websocket is not open")
        raw_message = await self.websocket.recv()
        if isinstance(raw_message, bytes):
            raw_message = raw_message.decode("utf-8")
        return json.loads(raw_message)

    async def close(self) -> None:
        if self.websocket is not None:
            await self.websocket.close()
            self.websocket = None


def build_sarvam_params(config: dict[str, Any]) -> dict[str, Any]:
    return dict(config.get("sarvamParams") or {})


def _int_param(params: dict[str, Any], key: str, default: int) -> int:
    try:
        return int(params.get(key, default))
    except (TypeError, ValueError):
        return int(default)


def _bool_param(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _bool_string(value: bool) -> str:
    return "true" if value else "false"
