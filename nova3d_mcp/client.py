"""
nova3d_mcp/client.py
────────────────────────────────────────────────────────────────
Async HTTP client for the Nova3D API.
Handles workflow submission, polling, and result extraction.
────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Dict, Optional

import httpx

from nova3d_mcp.models import (
    GenerationReadiness,
    GenerationResult,
    WorkflowStartResponse,
    WorkflowStatus,
)

# ── Constants ─────────────────────────────────────────────────────────────────

NOVA3D_API_BASE = "https://nova3d.xyz/api"
NOVA3D_PREVIEW_BASE = "https://nova3d.xyz/preview"

WORKFLOW_SKETCH_TO_3D = "sketch_to_3d"
WORKFLOW_REGENERATE_PART = "regenerate_3d_part"
WORKFLOW_ADD_PART = "add_3d_part"
WORKFLOW_ARTICULATE = "articulate_3d_model"

POLL_INTERVAL_SECONDS = 3.0
START_TIMEOUT_SECONDS = 120.0
RESULT_TIMEOUT_SECONDS = 300.0
CONNECT_TIMEOUT_SECONDS = 30.0

# Errors that are safe to retry — workflow may not be registered yet
RECOVERABLE_ERROR_SIGNALS = [
    "404",
    "workflow not found",
    "unavailable",
    "still starting",
    "timeout",
    "timed out",
    "request failed (null)",
    "request failed (502)",
    "request failed (503)",
    "request failed (504)",
]


# ── Exceptions ────────────────────────────────────────────────────────────────

class Nova3DError(Exception):
    """Raised for Nova3D API errors with a user-friendly message."""
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class Nova3DAuthError(Nova3DError):
    """Raised when authentication fails or the token is invalid/expired."""


class Nova3DCreditsError(Nova3DError):
    """Raised when the user has insufficient credits and no BYOK key."""


# ── Workflow ID ───────────────────────────────────────────────────────────────

def make_workflow_id() -> str:
    return f"state-{int(time.time() * 1_000_000)}"


# ── Client ────────────────────────────────────────────────────────────────────

class Nova3DClient:
    """
    Async client for the Nova3D generation API.

    Usage:
        async with Nova3DClient(token="your-jwt-token") as client:
            result = await client.generate(
                prompt="a toaster with removable tray",
                provider="google",
                llm="gemini-2.0-flash",
                api_key="AIza...",
            )
    """

    def __init__(
        self,
        token: str,
        base_url: str = NOVA3D_API_BASE,
        preview_base: str = NOVA3D_PREVIEW_BASE,
    ):
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._preview_base = preview_base.rstrip("/")
        self._http: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "Nova3DClient":
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(
                connect=CONNECT_TIMEOUT_SECONDS,
                read=RESULT_TIMEOUT_SECONDS,
                write=30.0,
                pool=5.0,
            ),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._token}",
            },
        )
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None

    # ── Public methods ────────────────────────────────────────────────────────

    async def check_readiness(self) -> GenerationReadiness:
        """Preflight check — confirm the generation service is available."""
        resp = await self._get(f"/workflow/readiness/{WORKFLOW_SKETCH_TO_3D}")
        return GenerationReadiness(**resp)

    async def generate(
        self,
        prompt: str,
        provider: str,
        llm: str,
        api_key: str,
        image_base64: Optional[str] = None,
        image_mime: Optional[str] = None,
        conversation_id: Optional[str] = None,
        on_progress: Optional[Callable[[WorkflowStatus], Awaitable[None]]] = None,
    ) -> GenerationResult:
        """
        Generate a 3D asset from a text prompt and optional reference image.
        Blocks until the workflow completes or fails.
        """
        readiness = await self.check_readiness()
        if not readiness.ready:
            raise Nova3DError(readiness.user_message)

        payload: Dict[str, Any] = {
            "prompt": prompt.strip(),
            "llm": llm,
            "provider": provider,
            "api_key": api_key,
        }
        if image_base64:
            payload["image_base64"] = image_base64
        if image_mime:
            payload["image_mime"] = image_mime

        workflow_id = await self._start_workflow(
            workflow=WORKFLOW_SKETCH_TO_3D,
            payload=payload,
            return_node="sketch_to_3d_generator",
            conversation_id=conversation_id,
        )
        return await self._poll_and_collect(workflow_id, on_progress=on_progress)

    async def regenerate_part(
        self,
        code_artifact: Dict[str, Any],
        part_type: str,
        description: str,
        provider: str,
        llm: str,
        api_key: str,
        conversation_id: Optional[str] = None,
        on_progress: Optional[Callable[[WorkflowStatus], Awaitable[None]]] = None,
    ) -> GenerationResult:
        """Regenerate a specific named part within an existing asset."""
        if not description.strip():
            raise Nova3DError("A description of the desired change is required.")
        if not part_type.strip():
            raise Nova3DError("A part name is required (e.g. 'door', 'handle').")

        payload: Dict[str, Any] = {
            "code_artifact": code_artifact,
            "description": description.strip(),
            "part_type": part_type.strip(),
            "llm": llm,
            "provider": provider,
            "api_key": api_key,
        }
        workflow_id = await self._start_workflow(
            workflow=WORKFLOW_REGENERATE_PART,
            payload=payload,
            return_node="regenerate_3d_part",
            conversation_id=conversation_id,
        )
        return await self._poll_and_collect(workflow_id, on_progress=on_progress)

    async def add_part(
        self,
        code_artifact: Dict[str, Any],
        description: str,
        provider: str,
        llm: str,
        api_key: str,
        conversation_id: Optional[str] = None,
        on_progress: Optional[Callable[[WorkflowStatus], Awaitable[None]]] = None,
    ) -> GenerationResult:
        """Add a new part to an existing asset."""
        if not description.strip():
            raise Nova3DError("A description of the new part is required.")

        payload: Dict[str, Any] = {
            "code_artifact": code_artifact,
            "description": description.strip(),
            "llm": llm,
            "provider": provider,
            "api_key": api_key,
        }
        workflow_id = await self._start_workflow(
            workflow=WORKFLOW_ADD_PART,
            payload=payload,
            return_node="add_3d_part",
            conversation_id=conversation_id,
        )
        return await self._poll_and_collect(workflow_id, on_progress=on_progress)

    async def articulate_model(
        self,
        code_artifact: Dict[str, Any],
        model_url: str,
        articulation_request: str,
        provider: str,
        llm: str,
        api_key: str,
        selected_meshes: Optional[list] = None,
        conversation_id: Optional[str] = None,
        on_progress: Optional[Callable[[WorkflowStatus], Awaitable[None]]] = None,
    ) -> GenerationResult:
        """Add joints, hinges, or rotation to an existing asset."""
        payload: Dict[str, Any] = {
            "code_artifact": code_artifact,
            "model_url": model_url,
            "articulation_request": articulation_request.strip(),
            "llm": llm,
            "provider": provider,
            "api_key": api_key,
        }
        if selected_meshes:
            payload["selected_meshes"] = selected_meshes

        workflow_id = await self._start_workflow(
            workflow=WORKFLOW_ARTICULATE,
            payload=payload,
            return_node="articulate_3d_model",
            conversation_id=conversation_id,
        )
        return await self._poll_and_collect(workflow_id, on_progress=on_progress)

    async def get_status(self, workflow_id: str) -> WorkflowStatus:
        """Get current workflow status."""
        resp = await self._get(f"/status/{workflow_id}")
        return WorkflowStatus.from_api(workflow_id, resp)

    async def get_result(self, workflow_id: str) -> GenerationResult:
        """Fetch final workflow result (blocking)."""
        resp = await self._get(
            f"/result/{workflow_id}",
            timeout=RESULT_TIMEOUT_SECONDS,
        )
        return GenerationResult.from_api(resp, workflow_id, self._preview_base.replace("/preview", ""))

    async def get_me(self) -> Dict[str, Any]:
        """Verify credentials and return user identity from GET /me."""
        return await self._get("/me")

    async def create_conversation(self, title: str) -> str:
        """Create a new conversation and return its ID."""
        resp = await self._post(
            "/conversations",
            json={
                "source": "mcp",
                "kind": "generation",
                "title": title[:255],
            },
        )
        conv_id = resp.get("id")
        if not conv_id:
            raise Nova3DError("Conversation creation did not return an ID.")
        return str(conv_id)

    def preview_url(self, workflow_id: str) -> str:
        return f"{self._preview_base}/{workflow_id}"

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _start_workflow(
        self,
        workflow: str,
        payload: Dict[str, Any],
        return_node: str,
        conversation_id: Optional[str] = None,
    ) -> str:
        """Submit a workflow and return the workflow_id."""
        workflow_id = make_workflow_id()
        body: Dict[str, Any] = {
            "payload": payload,
            "return_nodes": [return_node],
        }
        if conversation_id:
            body["conversation"] = {
                "conversation_id": conversation_id,
                "relation_type": "triggered_by",
            }
        try:
            resp = await self._post(
                f"/run/state/{workflow}",
                json=body,
                params={"request_id": workflow_id},
                timeout=START_TIMEOUT_SECONDS,
            )
        except httpx.TimeoutException:
            # Receive timeout — the workflow may have started anyway.
            # Return the original workflow_id and let polling sort it out.
            return workflow_id

        returned_id = resp.get("workflow_id") or ""
        if not returned_id:
            raise Nova3DError("Generation did not return a workflow ID.")
        return returned_id

    async def _poll_and_collect(
        self,
        workflow_id: str,
        on_progress: Optional[Callable[[WorkflowStatus], Awaitable[None]]] = None,
    ) -> GenerationResult:
        """Poll status until terminal, then fetch and return result."""
        while True:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            try:
                status = await self.get_status(workflow_id)
            except Nova3DError as e:
                if _is_recoverable(str(e)):
                    if on_progress:
                        await on_progress(WorkflowStatus(
                            workflow_id=workflow_id,
                            state="pending",  # type: ignore[arg-type]
                            current_node="sketch_to_3d_generator",
                        ))
                    continue
                raise

            if on_progress:
                await on_progress(status)

            if status.state.value == "budget_exhausted":
                raise Nova3DError(
                    "Your provider or generation budget was exhausted before the model completed."
                )
            if status.is_terminal:
                break

        # Fetch result with retry on recoverable errors
        while True:
            try:
                return await self.get_result(workflow_id)
            except Nova3DError as e:
                if not _is_recoverable(str(e)):
                    raise
                await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def _get(
        self,
        path: str,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        assert self._http is not None, "Client not started — use async with"
        try:
            kwargs: Dict[str, Any] = {}
            if timeout is not None:
                kwargs["timeout"] = timeout
            resp = await self._http.get(path, **kwargs)
            return self._handle_response(resp)
        except httpx.TimeoutException as e:
            raise Nova3DError(f"Request timed out: {e}")
        except httpx.NetworkError as e:
            raise Nova3DError(f"Network error: {e}")

    async def _post(
        self,
        path: str,
        json: Dict[str, Any],
        params: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        assert self._http is not None, "Client not started — use async with"
        try:
            kwargs: Dict[str, Any] = {"json": json}
            if params:
                kwargs["params"] = params
            if timeout is not None:
                kwargs["timeout"] = timeout
            resp = await self._http.post(path, **kwargs)
            return self._handle_response(resp)
        except httpx.TimeoutException as e:
            raise Nova3DError(f"Request timed out: {e}")
        except httpx.NetworkError as e:
            raise Nova3DError(f"Network error: {e}")

    def _handle_response(self, resp: httpx.Response) -> Dict[str, Any]:
        if resp.status_code == 401:
            _, message = _parse_auth_error(resp)
            raise Nova3DAuthError(message, status_code=401)
        if resp.status_code == 402:
            detail = ""
            try:
                body = resp.json()
                detail = body.get("message") or body.get("detail") or ""
            except Exception:
                pass
            raise Nova3DCreditsError(
                detail or "Add credits or provide your own provider API key to generate.",
                status_code=402,
            )
        if resp.status_code == 404:
            raise Nova3DError(f"workflow not found (404): {resp.text[:200]}", status_code=404)
        if resp.status_code >= 500:
            raise Nova3DError(
                f"request failed ({resp.status_code}): {resp.text[:200]}",
                status_code=resp.status_code,
            )
        if not resp.is_success:
            raise Nova3DError(
                f"request failed ({resp.status_code}): {resp.text[:200]}",
                status_code=resp.status_code,
            )
        try:
            return resp.json()
        except Exception as e:
            raise Nova3DError(f"Invalid JSON response: {e}")


# ── Utility ───────────────────────────────────────────────────────────────────

def _is_recoverable(error_message: str) -> bool:
    msg = error_message.lower()
    # Don't retry auth or budget errors
    if "sign in" in msg or "token" in msg or "budget" in msg:
        return False
    return any(signal in msg for signal in RECOVERABLE_ERROR_SIGNALS)


def _parse_auth_error(resp: httpx.Response) -> tuple[Optional[str], str]:
    """Parse a 401 response body for structured error code and user-facing message."""
    try:
        body = resp.json()
        detail = body.get("detail")
        if isinstance(detail, dict):
            code = detail.get("code")
            msg = detail.get("message", "")
            return code, _auth_message_for_code(code, msg)
        if isinstance(detail, str) and detail:
            return None, detail
    except Exception:
        pass
    return None, (
        "Nova3D authentication failed. "
        "Check your NOVA3D_TOKEN at nova3d.xyz → Settings → API Keys."
    )


def _auth_message_for_code(code: Optional[str], backend_message: str) -> str:
    if code == "api_key_revoked":
        return (
            "Your NOVA3D_TOKEN has been revoked. "
            "Create a new key at nova3d.xyz → Settings → API Keys."
        )
    if code == "invalid_api_key":
        return (
            "Your NOVA3D_TOKEN is invalid. "
            "Check or create a key at nova3d.xyz → Settings → API Keys."
        )
    return (
        backend_message
        or "Nova3D authentication failed. "
           "Check your NOVA3D_TOKEN at nova3d.xyz → Settings → API Keys."
    )
