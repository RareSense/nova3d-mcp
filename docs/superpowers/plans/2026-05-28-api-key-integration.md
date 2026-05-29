# API Key Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate Nova3D `n3d_` API keys into the MCP server: fix 401 error parsing, add hard startup validation via `GET /api/me`, surface `api_key_source` in tool responses, add `__main__.py`, and update README.

**Architecture:** Six targeted changes across three existing files plus one new file and a README update. No restructuring. TDD: all logic changes have tests in `tests/test_client.py` written before implementation. `_validate_startup` is tested by importing directly from `server.py` (import side-effects are safe — `load_dotenv` and `FastMCP(...)` are inert in tests).

**Tech Stack:** Python 3.10+, httpx, respx 0.21+, pytest-asyncio, mcp[cli]>=1.27.0

---

## File Map

| File | What changes |
|---|---|
| `nova3d-mcp/client.py` | Add `_parse_auth_error` + `_auth_message_for_code` helpers; update `_handle_response` 401 branch; add `get_me()` method |
| `nova3d-mcp/models.py` | Add optional `api_key_source: Optional[str]` field to `GenerationResult`; extract it in `from_api()` |
| `nova3d-mcp/server.py` | Add `import asyncio, sys`, import `Nova3DAuthError`; add `_validate_startup()`; update `main()`; add `api_key_source` to all four tool return dicts |
| `nova3d-mcp/__main__.py` | New file — enables `python -m nova3d_mcp` |
| `README.md` | Replace JWT setup with API key instructions |
| `tests/test_client.py` | New tests for auth error parsing, `get_me()`, `api_key_source` extraction, startup validation |

---

## Task 1: Fix 401 error parsing in `client.py`

**Files:**
- Modify: `nova3d-mcp/client.py`
- Test: `tests/test_client.py`

The current 401 handler raises a generic message. The backend returns
`{"detail": {"code": "api_key_revoked"|"invalid_api_key", "message": "..."}}`.
We need to parse that and surface the right message.

- [ ] **Step 1: Write failing tests**

Add to `tests/test_client.py`:

```python
from nova3d_mcp.client import _parse_auth_error, Nova3DAuthError


def test_parse_auth_error_revoked():
    resp = httpx.Response(401, json={
        "detail": {"code": "api_key_revoked", "message": "Key revoked."}
    })
    code, message = _parse_auth_error(resp)
    assert code == "api_key_revoked"
    assert "revoked" in message.lower()
    assert "nova3d.xyz" in message


def test_parse_auth_error_invalid_key():
    resp = httpx.Response(401, json={
        "detail": {"code": "invalid_api_key", "message": "Bad key."}
    })
    code, message = _parse_auth_error(resp)
    assert code == "invalid_api_key"
    assert "invalid" in message.lower()
    assert "nova3d.xyz" in message


def test_parse_auth_error_detail_string():
    # JWT path — FastAPI returns detail as a plain string
    resp = httpx.Response(401, json={"detail": "Not authenticated"})
    code, message = _parse_auth_error(resp)
    assert code is None
    assert message == "Not authenticated"


def test_parse_auth_error_no_json():
    resp = httpx.Response(401, content=b"Unauthorized")
    code, message = _parse_auth_error(resp)
    assert code is None
    assert "nova3d.xyz" in message


@pytest.mark.asyncio
async def test_generate_raises_auth_error_with_code(mock_api):
    mock_api.get("/workflow/readiness/sketch_to_3d").mock(
        return_value=httpx.Response(200, json=_readiness_ok())
    )
    mock_api.post("/run/state/sketch_to_3d").mock(
        return_value=httpx.Response(401, json={
            "detail": {"code": "api_key_revoked", "message": "Revoked."}
        })
    )
    async with Nova3DClient(token=FAKE_TOKEN, base_url=BASE_URL) as client:
        with pytest.raises(Nova3DAuthError, match="revoked"):
            await client.generate(
                prompt="a robot",
                provider="google",
                llm="gemini-2.0-flash",
                api_key="n3d_test",
            )
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_client.py::test_parse_auth_error_revoked tests/test_client.py::test_parse_auth_error_invalid_key tests/test_client.py::test_parse_auth_error_detail_string tests/test_client.py::test_parse_auth_error_no_json tests/test_client.py::test_generate_raises_auth_error_with_code -v
```

Expected: `ImportError` or `FAILED` — `_parse_auth_error` does not exist yet.

- [ ] **Step 3: Add `_parse_auth_error` and `_auth_message_for_code` to `client.py`**

Add after the `_is_recoverable` function at the bottom of `nova3d-mcp/client.py`:

```python
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
```

- [ ] **Step 4: Update the 401 branch in `_handle_response()`**

In `nova3d-mcp/client.py`, replace:

```python
        if resp.status_code == 401:
            raise Nova3DAuthError(
                "Nova3D rejected the authentication token. "
                "Please sign in again and update your NOVA3D_TOKEN.",
                status_code=401,
            )
```

With:

```python
        if resp.status_code == 401:
            _, message = _parse_auth_error(resp)
            raise Nova3DAuthError(message, status_code=401)
```

- [ ] **Step 5: Run tests to confirm they pass**

```bash
pytest tests/test_client.py::test_parse_auth_error_revoked tests/test_client.py::test_parse_auth_error_invalid_key tests/test_client.py::test_parse_auth_error_detail_string tests/test_client.py::test_parse_auth_error_no_json tests/test_client.py::test_generate_raises_auth_error_with_code -v
```

Expected: all 5 PASSED.

- [ ] **Step 6: Run full test suite to confirm no regressions**

```bash
pytest -v
```

Expected: all existing tests still pass.

- [ ] **Step 7: Commit**

```bash
git add nova3d-mcp/client.py tests/test_client.py
git commit -m "fix: parse detail.code from 401 responses for actionable auth errors"
```

---

## Task 2: Add `get_me()` to `Nova3DClient` in `client.py`

**Files:**
- Modify: `nova3d-mcp/client.py`
- Test: `tests/test_client.py`

`GET /api/me` returns `{user_id, email, available_credits, tenant_id}`. Used by startup validation.

- [ ] **Step 1: Write failing test**

Add to `tests/test_client.py`:

```python
@pytest.mark.asyncio
async def test_get_me_success(mock_api):
    mock_api.get("/me").mock(
        return_value=httpx.Response(200, json={
            "user_id": "b333345d-a36c-487e-9096-5f7fd9a2901b",
            "email": "hassan@raresense.so",
            "available_credits": 1000,
            "tenant_id": "ten_e06a051bdb1f43b7b9d5bfaea1e07bf0",
        })
    )
    async with Nova3DClient(token=FAKE_TOKEN, base_url=BASE_URL) as client:
        me = await client.get_me()
    assert me["email"] == "hassan@raresense.so"
    assert me["available_credits"] == 1000


@pytest.mark.asyncio
async def test_get_me_invalid_key(mock_api):
    mock_api.get("/me").mock(
        return_value=httpx.Response(401, json={
            "detail": {"code": "invalid_api_key", "message": "Bad key."}
        })
    )
    async with Nova3DClient(token="n3d_bad", base_url=BASE_URL) as client:
        with pytest.raises(Nova3DAuthError, match="invalid"):
            await client.get_me()
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_client.py::test_get_me_success tests/test_client.py::test_get_me_invalid_key -v
```

Expected: `FAILED` — `Nova3DClient` has no `get_me` method.

- [ ] **Step 3: Add `get_me()` to `Nova3DClient`**

In `nova3d-mcp/client.py`, add after the `get_result` method (around line 265):

```python
    async def get_me(self) -> Dict[str, Any]:
        """Verify credentials and return user identity from GET /me."""
        return await self._get("/me")
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_client.py::test_get_me_success tests/test_client.py::test_get_me_invalid_key -v
```

Expected: both PASSED.

- [ ] **Step 5: Commit**

```bash
git add nova3d-mcp/client.py tests/test_client.py
git commit -m "feat: add get_me() to Nova3DClient for startup credential validation"
```

---

## Task 3: Add `api_key_source` to `GenerationResult` in `models.py`

**Files:**
- Modify: `nova3d-mcp/models.py`
- Test: `tests/test_client.py`

`api_key_source` is in the raw generation result (`"request"` / `"server"` / `"server_fallback"`). Currently discarded. Add as optional field on `GenerationResult`.

- [ ] **Step 1: Write failing tests**

Add to `tests/test_client.py`:

```python
def test_result_parsing_api_key_source_present():
    data = {
        "sketch_to_3d_generator": [
            {
                "result": {
                    "model_url": "https://nova3d.xyz/assets/abc123.glb",
                    "model_artifact": {"url": "https://nova3d.xyz/assets/abc123.glb"},
                    "code_artifact": {"content": "import bpy"},
                    "api_key_source": "request",
                }
            }
        ]
    }
    result = GenerationResult.from_api(data, WORKFLOW_ID)
    assert result.api_key_source == "request"


def test_result_parsing_api_key_source_absent():
    result = GenerationResult.from_api(_result_ok(), WORKFLOW_ID)
    assert result.api_key_source is None
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_client.py::test_result_parsing_api_key_source_present tests/test_client.py::test_result_parsing_api_key_source_absent -v
```

Expected: `FAILED` — `GenerationResult` has no `api_key_source` field.

- [ ] **Step 3: Add field to `GenerationResult`**

In `nova3d-mcp/models.py`, in the `GenerationResult` class body, add after `retryable`:

```python
    api_key_source: Optional[str] = None
```

- [ ] **Step 4: Extract the field in `from_api()`**

In the `from_api()` classmethod in `nova3d-mcp/models.py`, add after the `operation = ...` line:

```python
        api_key_source = _str_val(unwrapped.get("api_key_source"))
```

Then add it to the `cls(...)` constructor call:

```python
        return cls(
            glb_url=glb_url,
            preview_url=preview_url,
            model_artifact=model_artifact,
            code_artifact=code_artifact,
            joints_artifact=joints_artifact,
            joints=joints,
            joint_count=joint_count,
            parts=parts,
            operation=operation,
            api_key_source=api_key_source,
            failed=failed,
            error_message=error_message,
            error_category=failure.get("category") if failure else None,
            retryable=failure.get("retryable", False) if failure else False,
            workflow_id=workflow_id,
        )
```

- [ ] **Step 5: Run tests to confirm they pass**

```bash
pytest tests/test_client.py::test_result_parsing_api_key_source_present tests/test_client.py::test_result_parsing_api_key_source_absent -v
```

Expected: both PASSED.

- [ ] **Step 6: Run full test suite**

```bash
pytest -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add nova3d-mcp/models.py tests/test_client.py
git commit -m "feat: extract api_key_source from generation results"
```

---

## Task 4: Add startup validation to `server.py`

**Files:**
- Modify: `nova3d-mcp/server.py`
- Test: `tests/test_client.py`

`main()` must call `_validate_startup()` before `mcp.run()`. On missing/invalid token: print a clear message and exit 1. On success: print `✓ Nova3D authenticated: {email}`.

- [ ] **Step 1: Write failing tests**

Add to `tests/test_client.py`:

```python
import respx as _respx
from nova3d_mcp.server import _validate_startup


@pytest.mark.asyncio
async def test_validate_startup_no_token(monkeypatch, capsys):
    monkeypatch.delenv("NOVA3D_TOKEN", raising=False)
    with pytest.raises(SystemExit) as exc_info:
        await _validate_startup()
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "NOVA3D_TOKEN is not set" in captured.err


@pytest.mark.asyncio
async def test_validate_startup_success(mock_api, monkeypatch, capsys):
    monkeypatch.setenv("NOVA3D_TOKEN", "n3d_validkey")
    mock_api.get("/me").mock(
        return_value=httpx.Response(200, json={
            "user_id": "abc",
            "email": "test@example.com",
            "available_credits": 0,
            "tenant_id": "ten_abc",
        })
    )
    await _validate_startup()  # must not raise
    captured = capsys.readouterr()
    assert "test@example.com" in captured.err


@pytest.mark.asyncio
async def test_validate_startup_revoked_key(mock_api, monkeypatch, capsys):
    monkeypatch.setenv("NOVA3D_TOKEN", "n3d_revoked")
    mock_api.get("/me").mock(
        return_value=httpx.Response(401, json={
            "detail": {"code": "api_key_revoked", "message": "Revoked."}
        })
    )
    with pytest.raises(SystemExit) as exc_info:
        await _validate_startup()
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "revoked" in captured.err.lower()


@pytest.mark.asyncio
async def test_validate_startup_network_error(monkeypatch, capsys):
    monkeypatch.setenv("NOVA3D_TOKEN", "n3d_testkey")
    with _respx.mock(base_url=BASE_URL) as mock:
        mock.get("/me").mock(side_effect=httpx.NetworkError("Connection refused"))
        with pytest.raises(SystemExit) as exc_info:
            await _validate_startup()
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "connection" in captured.err.lower() or "network" in captured.err.lower()
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_client.py::test_validate_startup_no_token tests/test_client.py::test_validate_startup_success tests/test_client.py::test_validate_startup_revoked_key tests/test_client.py::test_validate_startup_network_error -v
```

Expected: `ImportError` — `_validate_startup` does not exist yet.

- [ ] **Step 3: Add imports to `server.py`**

In `nova3d-mcp/server.py`, replace the existing import block at the top:

```python
from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from nova3d_mcp.client import Nova3DClient, Nova3DAuthError, Nova3DError
from nova3d_mcp.models import PROVIDER_DEFAULT_MODELS
```

- [ ] **Step 4: Add `_validate_startup()` to `server.py`**

Add after the `_get_api_url()` function and before the `# ── Tools` comment:

```python
async def _validate_startup() -> None:
    """Validate NOVA3D_TOKEN against GET /api/me before accepting any tool calls."""
    token = os.environ.get("NOVA3D_TOKEN", "").strip()
    if not token:
        print(
            "Nova3D: NOVA3D_TOKEN is not set.\n"
            "Create an API key at https://nova3d.xyz/settings → API Keys,\n"
            "then set it as NOVA3D_TOKEN in your MCP config and restart.",
            file=sys.stderr,
        )
        sys.exit(1)

    base_url = _get_api_url()
    try:
        async with Nova3DClient(token=token, base_url=base_url) as client:
            me = await client.get_me()
        print(f"✓ Nova3D authenticated: {me['email']}", file=sys.stderr)
    except Nova3DAuthError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
    except Nova3DError as e:
        print(
            f"Could not reach Nova3D to verify token: {e}\n"
            "Check your connection and try again.",
            file=sys.stderr,
        )
        sys.exit(1)
```

- [ ] **Step 5: Update `main()` in `server.py`**

Replace:

```python
def main() -> None:
    mcp.run()
```

With:

```python
def main() -> None:
    asyncio.run(_validate_startup())
    mcp.run()
```

- [ ] **Step 6: Run tests to confirm they pass**

```bash
pytest tests/test_client.py::test_validate_startup_no_token tests/test_client.py::test_validate_startup_success tests/test_client.py::test_validate_startup_revoked_key tests/test_client.py::test_validate_startup_network_error -v
```

Expected: all 4 PASSED.

- [ ] **Step 7: Run full test suite**

```bash
pytest -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add nova3d-mcp/server.py tests/test_client.py
git commit -m "feat: hard startup validation via GET /api/me — fail fast on missing or invalid token"
```

---

## Task 5: Surface `api_key_source` in all tool responses

**Files:**
- Modify: `nova3d-mcp/server.py`

All four generation tools currently discard `result.api_key_source`. Add it to each success return dict. The field is already on `GenerationResult` (Task 3). No new tests needed — the existing `test_generate_success` already verifies the tool runs end-to-end; update it to assert the new field is present.

- [ ] **Step 1: Update `test_generate_success` to assert `api_key_source`**

In `tests/test_client.py`, in `test_generate_success`, add after the existing assertions:

```python
    assert "api_key_source" in result.__dict__ or result.api_key_source is None
```

Wait — `test_generate_success` tests `Nova3DClient.generate()` directly, which returns a `GenerationResult`, not a tool response dict. The tool response dict is what `server.py` returns. We don't have a direct test for the tool layer (tools use the FastMCP framework). Instead, verify by checking the `GenerationResult` field is wired through.

Replace the step above with: in `test_result_parsing_api_key_source_present` (already written in Task 3), confirm `result.api_key_source == "request"`. That's sufficient — the tool simply passes `result.api_key_source` through.

- [ ] **Step 2: Add `api_key_source` to `generate_3d` return dict**

In `nova3d-mcp/server.py`, in the `generate_3d` tool, replace the success return:

```python
    return {
        "glb_url": result.glb_url,
        "preview_url": result.preview_url,
        "parts": result.parts,
        "joint_count": result.joint_count,
        "joints": result.joints,
        "code_artifact": result.code_artifact,
        "model_artifact": result.model_artifact,
        "workflow_id": result.workflow_id,
        "api_key_source": result.api_key_source,
        "failed": False,
    }
```

- [ ] **Step 3: Add `api_key_source` to `regenerate_part` return dict**

```python
    return {
        "glb_url": result.glb_url,
        "preview_url": result.preview_url,
        "parts": result.parts,
        "code_artifact": result.code_artifact,
        "workflow_id": result.workflow_id,
        "api_key_source": result.api_key_source,
        "failed": False,
    }
```

- [ ] **Step 4: Add `api_key_source` to `add_part` return dict**

```python
    return {
        "glb_url": result.glb_url,
        "preview_url": result.preview_url,
        "parts": result.parts,
        "code_artifact": result.code_artifact,
        "workflow_id": result.workflow_id,
        "api_key_source": result.api_key_source,
        "failed": False,
    }
```

- [ ] **Step 5: Add `api_key_source` to `articulate_model` return dict**

```python
    return {
        "glb_url": result.glb_url,
        "preview_url": result.preview_url,
        "joints": result.joints,
        "joint_count": result.joint_count,
        "code_artifact": result.code_artifact,
        "workflow_id": result.workflow_id,
        "api_key_source": result.api_key_source,
        "failed": False,
    }
```

- [ ] **Step 6: Run full test suite**

```bash
pytest -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add nova3d-mcp/server.py
git commit -m "feat: include api_key_source in all generation tool responses"
```

---

## Task 6: Create `nova3d-mcp/__main__.py`

**Files:**
- Create: `nova3d-mcp/__main__.py`

Enables `python -m nova3d_mcp`.

- [ ] **Step 1: Create the file**

Create `nova3d-mcp/__main__.py` with:

```python
from nova3d_mcp.server import main

main()
```

- [ ] **Step 2: Verify it's importable**

```bash
python -c "import nova3d_mcp.__main__"
```

Expected: no output, no error. (Requires `uv sync` or `pip install -e .` first.)

- [ ] **Step 3: Commit**

```bash
git add "nova3d-mcp/__main__.py"
git commit -m "fix: add __main__.py to enable python -m nova3d_mcp"
```

---

## Task 7: Update `README.md`

**Files:**
- Modify: `README.md`

Replace the JWT-based setup in the Quickstart with API key instructions.

- [ ] **Step 1: Replace Step 2 in the Quickstart section**

Find and replace the `### 2. Configure` section in `README.md`:

Replace:
```markdown
### 2. Configure

Get your Nova3D token from [nova3d.xyz](https://nova3d.xyz) → Settings.

```bash
export NOVA3D_TOKEN="your-nova3d-jwt-token"
```
```

With:
```markdown
### 2. Get an API key

Sign in at [nova3d.xyz](https://nova3d.xyz), go to **Settings → API Keys**, and create a key.

```bash
export NOVA3D_TOKEN="n3d_your-api-key-here"
```

API keys never expire unless revoked. The MCP server validates your key on startup
and prints a clear error if it's missing or invalid.
```

- [ ] **Step 2: Update the Claude Code config example**

In `### 3. Add to Claude Code`, replace `"your-nova3d-jwt-token"` with `"n3d_your-api-key-here"`.

- [ ] **Step 3: Update the Environment variables table**

In the `## Environment variables` section, update the `NOVA3D_TOKEN` description:

```markdown
| `NOVA3D_TOKEN` | ✓ | API key from nova3d.xyz → Settings → API Keys (recommended) or session JWT |
```

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: update README for API key auth — replace JWT setup instructions"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Covered by |
|---|---|
| `_handle_response()` parses `detail.code` | Task 1 |
| `detail` as string handled as fallback | Task 1, Step 3 |
| Generic fallback message | Task 1, Step 3 |
| `get_me()` method on client | Task 2 |
| `api_key_source` on `GenerationResult` | Task 3 |
| `_validate_startup()` checks missing token | Task 4 |
| `_validate_startup()` prints email on success | Task 4 |
| `_validate_startup()` handles 401 with code | Task 4 |
| `_validate_startup()` handles network error | Task 4 |
| `main()` calls `asyncio.run(_validate_startup())` | Task 4 |
| `api_key_source` in all four tool responses | Task 5 |
| `__main__.py` | Task 6 |
| README updated | Task 7 |

**No placeholders found.** All steps contain complete code.

**Type consistency:** `api_key_source: Optional[str]` defined in Task 3, used as `result.api_key_source` in Task 5. `get_me()` returns `Dict[str, Any]`, consumed as `me["email"]` in Task 4. Consistent throughout.
