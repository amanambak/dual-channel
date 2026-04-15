import json
from urllib.parse import urlencode

import websockets
from websockets.asyncio.client import ClientConnection

from app.core.config import get_settings


class DeepgramClient:
    def __init__(self, params: dict | None = None) -> None:
        self.settings = get_settings()
        self.params = params or {}
        self.connection: ClientConnection | None = None

    async def connect(self) -> ClientConnection:
        query = urlencode(self.params)
        url = self.settings.deepgram_ws_url
        if query:
            url = f"{url}?{query}"

        self.connection = await websockets.connect(
            url,
            additional_headers={"Authorization": f"Token {self.settings.deepgram_api_key}"},
            max_size=2**24,
        )
        return self.connection

    async def send_audio(self, payload: bytes) -> None:
        if self.connection is None:
            return
        await self.connection.send(payload)

    async def send_close(self) -> None:
        if self.connection is None:
            return
        await self.connection.send(json.dumps({"type": "CloseStream"}))

    async def recv(self) -> str:
        if self.connection is None:
            raise RuntimeError("Deepgram connection is not open")
        return await self.connection.recv()

    async def close(self) -> None:
        if self.connection is not None:
            await self.connection.close()
            self.connection = None
