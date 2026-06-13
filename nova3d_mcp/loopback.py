from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Dict, Optional
from urllib.parse import parse_qs, urlparse


@dataclass
class LoopbackCallback:
    code: Optional[str]
    state: Optional[str]
    raw_query: Dict[str, str]


class LoopbackServer:
    def __init__(self) -> None:
        self._server: Optional[asyncio.base_events.Server] = None
        self._callback_future: asyncio.Future[LoopbackCallback] = (
            asyncio.get_running_loop().create_future()
        )
        self._port: Optional[int] = None

    @property
    def port(self) -> int:
        if self._port is None:
            raise RuntimeError("Loopback server is not started.")
        return self._port

    async def start(self) -> int:
        self._server = await asyncio.start_server(
            self._handle_connection,
            host="127.0.0.1",
            port=0,
        )
        sockets = self._server.sockets or []
        if not sockets:
            raise RuntimeError("Loopback listener did not bind a socket.")
        self._port = int(sockets[0].getsockname()[1])
        return self._port

    async def wait_for_callback(self, timeout_seconds: float) -> LoopbackCallback:
        return await asyncio.wait_for(self._callback_future, timeout=timeout_seconds)

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            request_line = await reader.readline()
            path = "/"
            if request_line:
                parts = request_line.decode("utf-8", errors="replace").split()
                if len(parts) >= 2:
                    path = parts[1]

            while True:
                line = await reader.readline()
                if not line or line in (b"\r\n", b"\n"):
                    break

            parsed = urlparse(path)
            query_items = {
                key: values[-1]
                for key, values in parse_qs(parsed.query).items()
                if values
            }
            callback = LoopbackCallback(
                code=query_items.get("code"),
                state=query_items.get("state"),
                raw_query=query_items,
            )
            if not self._callback_future.done():
                self._callback_future.set_result(callback)

            body = (
                "<html><body><h1>Nova3D connected</h1>"
                "<p>You can return to your editor now.</p></body></html>"
            )
            response = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: text/html; charset=utf-8\r\n"
                f"Content-Length: {len(body.encode('utf-8'))}\r\n"
                "Connection: close\r\n\r\n"
                f"{body}"
            )
            writer.write(response.encode("utf-8"))
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
