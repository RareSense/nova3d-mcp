from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional


def _default_session_path() -> Path:
    override = os.environ.get("NOVA3D_SESSION_PATH", "").strip()
    if override:
        return Path(override).expanduser()

    xdg_state_home = os.environ.get("XDG_STATE_HOME", "").strip()
    if xdg_state_home:
        root = Path(xdg_state_home).expanduser()
    else:
        root = Path.home() / ".local" / "state"
    return root / "nova3d" / "mcp-session.json"


class SessionStore:
    def __init__(self, path: Optional[Path] = None):
        self._path = path or _default_session_path()

    @property
    def path(self) -> Path:
        return self._path

    def load_token(self) -> Optional[str]:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except json.JSONDecodeError:
            return None

        token = payload.get("token")
        if isinstance(token, str) and token.strip():
            return token.strip()
        return None

    def save_token(self, token: str) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"token": token.strip()}
        self._path.write_text(json.dumps(payload), encoding="utf-8")
        try:
            os.chmod(self._path, 0o600)
        except OSError:
            pass

    def clear(self) -> None:
        try:
            self._path.unlink()
        except FileNotFoundError:
            return
