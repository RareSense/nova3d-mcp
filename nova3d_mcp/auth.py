from __future__ import annotations

import secrets
import webbrowser
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlencode

from nova3d_mcp.client import Nova3DClient, Nova3DError
from nova3d_mcp.loopback import LoopbackServer
from nova3d_mcp.models import MCPStatus
from nova3d_mcp.session_store import SessionStore

LOGIN_TIMEOUT_SECONDS = 300.0


@dataclass
class LoginResult:
    token: str
    status: MCPStatus
    connect_url: str
    port: int


class Nova3DAuthenticator:
    def __init__(
        self,
        *,
        base_url: str,
        app_url: str,
        session_store: SessionStore,
    ) -> None:
        self._base_url = base_url
        self._app_url = app_url.rstrip("/")
        self._session_store = session_store

    async def login(self) -> LoginResult:
        state = secrets.token_urlsafe(32)
        loopback = LoopbackServer()
        try:
            port = await loopback.start()
        except OSError as e:
            raise Nova3DError(
                "Nova3D sign-in could not start a local callback listener. "
                "Use the advanced NOVA3D_TOKEN setup path in this environment."
            ) from e

        connect_url = self._build_connect_url(state=state, port=port)
        opened = webbrowser.open(connect_url)
        if not opened:
            await loopback.close()
            raise Nova3DError(
                "Nova3D could not open your browser automatically. "
                f"Open this URL manually: {connect_url}"
            )

        try:
            callback = await loopback.wait_for_callback(LOGIN_TIMEOUT_SECONDS)
        finally:
            await loopback.close()

        if callback.state != state:
            raise Nova3DError("Nova3D sign-in callback state mismatch. Try signing in again.")
        if not callback.code:
            raise Nova3DError("Nova3D sign-in callback did not include a session code.")

        async with Nova3DClient(token=None, base_url=self._base_url) as client:
            token = await client.exchange_mcp_session_code(callback.code)

        self._session_store.save_token(token)

        async with Nova3DClient(token=token, base_url=self._base_url) as client:
            status = await client.get_mcp_status()

        return LoginResult(
            token=token,
            status=status,
            connect_url=connect_url,
            port=port,
        )

    def _build_connect_url(self, *, state: str, port: int) -> str:
        query = urlencode({"state": state, "port": str(port)})
        return f"{self._app_url}/mcp/connect?{query}"
