# Startup Error UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the MCP server running even when `NOVA3D_TOKEN` is missing or invalid, and surface actionable error messages in-conversation instead of burying them in debug logs.

**Architecture:** Add a module-level `_startup_error` flag in `server.py`. `_validate_startup()` stores the error instead of calling `sys.exit(1)`. Each of the 5 tools checks the flag first and returns a `{"failed": True, "error_message": ...}` dict if set. The `mcp` instructions string is updated to tell Claude to proactively guide users through setup when no token is configured.

**Tech Stack:** Python 3.10+, FastMCP, pytest, asyncio

---

### Task 1: Add error flag and update `_validate_startup()`

**Files:**
- Modify: `nova3d_mcp/server.py`
- Test: `tests/test_server.py` (create new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_server.py`:

```python
"""
tests/test_server.py
────────────────────────────────────────────────────────────────
Tests for server-level startup error propagation.
────────────────────────────────────────────────────────────────
"""
import pytest
import nova3d_mcp.server as server_module


@pytest.fixture(autouse=True)
def reset_startup_error():
    """Reset _startup_error before and after every test."""
    server_module._startup_error = None
    yield
    server_module._startup_error = None


@pytest.mark.asyncio
async def test_generate_3d_returns_error_when_startup_failed():
    server_module._startup_error = (
        "Your NOVA3D_TOKEN is invalid. "
        "Check or create a key at nova3d.xyz → Settings → API Keys."
    )
    result = await server_module.generate_3d(
        prompt="a chair",
        provider="google",
        api_key="fake",
    )
    assert result["failed"] is True
    assert "nova3d.xyz" in result["error_message"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
source .venv/bin/activate && pytest tests/test_server.py::test_generate_3d_returns_error_when_startup_failed -v
```

Expected: `FAILED` — `_startup_error` attribute does not exist yet.

- [ ] **Step 3: Add the error flag to `server.py`**

After the `load_dotenv()` line (line 32) and before the `# ── Server init ──` comment, add:

```python
# ── Startup error state ───────────────────────────────────────────────────────

_startup_error: Optional[str] = None
```

- [ ] **Step 4: Update `_validate_startup()` to store instead of exit**

Replace the entire `_validate_startup` function (currently lines 67–93) with:

```python
async def _validate_startup() -> None:
    """Validate NOVA3D_TOKEN against GET /api/me. Stores error in _startup_error instead of exiting."""
    global _startup_error

    token = os.environ.get("NOVA3D_TOKEN", "").strip()
    if not token:
        _startup_error = (
            "NOVA3D_TOKEN is not set. "
            "Create an API key at https://nova3d.xyz/settings → API Keys, "
            "then set it as NOVA3D_TOKEN in your MCP config and restart."
        )
        print(
            f"Nova3D: {_startup_error}",
            file=sys.stderr,
        )
        return

    base_url = _get_api_url()
    try:
        async with Nova3DClient(token=token, base_url=base_url) as client:
            me = await client.get_me()
        print(f"✓ Nova3D authenticated: {me['email']}", file=sys.stderr)
    except Nova3DAuthError as e:
        _startup_error = str(e)
        print(_startup_error, file=sys.stderr)
    except Nova3DError as e:
        _startup_error = (
            f"Could not reach Nova3D to verify token: {e}\n"
            "Check your connection and try again."
        )
        print(_startup_error, file=sys.stderr)
```

- [ ] **Step 5: Run test to verify it passes**

```bash
source .venv/bin/activate && pytest tests/test_server.py::test_generate_3d_returns_error_when_startup_failed -v
```

Expected: still `FAILED` — `generate_3d` doesn't check `_startup_error` yet. That's correct; we implement the guard in Task 2.

- [ ] **Step 6: Commit**

```bash
git add nova3d_mcp/server.py tests/test_server.py
git commit -m "feat: add _startup_error flag, store auth errors instead of sys.exit"
```

---

### Task 2: Add guard to all 5 tools

**Files:**
- Modify: `nova3d_mcp/server.py`
- Modify: `tests/test_server.py`

- [ ] **Step 1: Add guard to `generate_3d`**

In `generate_3d`, insert as the very first line of the function body (before `resolved_llm = ...`):

```python
    if _startup_error:
        return {"failed": True, "error_message": _startup_error}
```

- [ ] **Step 2: Run the existing test — it should now pass**

```bash
source .venv/bin/activate && pytest tests/test_server.py::test_generate_3d_returns_error_when_startup_failed -v
```

Expected: `PASSED`

- [ ] **Step 3: Add guards to the remaining 4 tools**

Add the same two lines as the very first line of the function body in each of:
- `regenerate_part` (before `resolved_llm = ...`)
- `add_part` (before `resolved_llm = ...`)
- `articulate_model` (before `resolved_llm = ...`)
- `get_generation_status` (before `token = _get_token()`)

- [ ] **Step 4: Write tests for the remaining 4 tools and the regression guard**

Add to `tests/test_server.py`:

```python
@pytest.mark.asyncio
async def test_regenerate_part_returns_error_when_startup_failed():
    server_module._startup_error = "Your NOVA3D_TOKEN is invalid. Check or create a key at nova3d.xyz → Settings → API Keys."
    result = await server_module.regenerate_part(
        code_artifact={},
        part_type="door",
        description="glass door",
        provider="google",
        api_key="fake",
    )
    assert result["failed"] is True
    assert "nova3d.xyz" in result["error_message"]


@pytest.mark.asyncio
async def test_add_part_returns_error_when_startup_failed():
    server_module._startup_error = "Your NOVA3D_TOKEN is invalid. Check or create a key at nova3d.xyz → Settings → API Keys."
    result = await server_module.add_part(
        code_artifact={},
        description="a handle",
        provider="google",
        api_key="fake",
    )
    assert result["failed"] is True
    assert "nova3d.xyz" in result["error_message"]


@pytest.mark.asyncio
async def test_articulate_model_returns_error_when_startup_failed():
    server_module._startup_error = "Your NOVA3D_TOKEN is invalid. Check or create a key at nova3d.xyz → Settings → API Keys."
    result = await server_module.articulate_model(
        code_artifact={},
        model_url="https://nova3d.xyz/assets/abc.glb",
        articulation_request="make door swing",
        provider="google",
        api_key="fake",
    )
    assert result["failed"] is True
    assert "nova3d.xyz" in result["error_message"]


@pytest.mark.asyncio
async def test_get_generation_status_returns_error_when_startup_failed():
    server_module._startup_error = "Your NOVA3D_TOKEN is invalid. Check or create a key at nova3d.xyz → Settings → API Keys."
    result = await server_module.get_generation_status(workflow_id="state-123")
    assert result["failed"] is True
    assert "nova3d.xyz" in result["error_message"]


@pytest.mark.asyncio
async def test_generate_3d_proceeds_when_no_startup_error(monkeypatch):
    """Regression guard: no startup error means the tool runs normally, not short-circuited by the flag."""
    import respx
    import httpx

    server_module._startup_error = None
    monkeypatch.setenv("NOVA3D_TOKEN", "fake-token")

    # Mock the readiness check to return a 401 — proves the tool reached the network call,
    # meaning the guard did NOT short-circuit it.
    with respx.mock(base_url="https://nova3d.xyz/api", assert_all_called=False):
        respx.get("/workflow/readiness/sketch_to_3d").mock(
            return_value=httpx.Response(401, json={"detail": {"code": "invalid_api_key", "message": "bad key"}})
        )
        from nova3d_mcp.client import Nova3DAuthError
        with pytest.raises(Nova3DAuthError):
            await server_module.generate_3d(prompt="a chair", provider="google", api_key="fake")
```

- [ ] **Step 5: Run all server tests**

```bash
source .venv/bin/activate && pytest tests/test_server.py -v
```

Expected: all 6 tests `PASSED`

- [ ] **Step 6: Run full test suite to check for regressions**

```bash
source .venv/bin/activate && pytest -v
```

Expected: all tests `PASSED` (existing `test_client.py` tests unaffected)

- [ ] **Step 7: Commit**

```bash
git add nova3d_mcp/server.py tests/test_server.py
git commit -m "feat: guard all tools against startup auth errors, return friendly error dict"
```

---

### Task 3: Update `mcp` instructions for proactive setup guidance

**Files:**
- Modify: `nova3d_mcp/server.py`

- [ ] **Step 1: Replace the `instructions` string in the `FastMCP` constructor**

Find the `mcp = FastMCP(...)` block (around line 36) and replace the `instructions` value with:

```python
mcp = FastMCP(
    "nova3d",
    instructions=(
        "Nova3D generates structured, part-aware 3D assets from text prompts or "
        "reference images. Unlike diffusion-based tools, Nova3D outputs named, "
        "separately editable mesh components — not fused blobs. "
        "Each tool call returns a GLB download URL and a browser preview URL "
        "where you can inspect and interact with the generated parts. "
        "\n\n"
        "SETUP: This server requires two credentials:\n"
        "1. NOVA3D_TOKEN — a Nova3D API key. If the user has not set this, "
        "proactively tell them: 'To use Nova3D, you need an API key. "
        "Get one at https://nova3d.xyz/settings → API Keys, then run: "
        "claude mcp add nova3d -e NOVA3D_TOKEN=n3d_your-key -- uvx nova3d-mcp'\n"
        "2. A BYOK provider key (Google, Anthropic, or OpenAI) passed as `api_key` in each tool call.\n"
        "\n"
        "If any tool returns {\"failed\": true}, surface the error_message to the user verbatim."
    ),
)
```

- [ ] **Step 2: Run full test suite**

```bash
source .venv/bin/activate && pytest -v
```

Expected: all tests `PASSED` — instructions change has no effect on tests.

- [ ] **Step 3: Smoke-test startup with no token**

```bash
source .venv/bin/activate && NOVA3D_TOKEN="" python -m nova3d_mcp.server 2>&1 &
sleep 2 && kill %1
```

Expected stderr output:
```
Nova3D: NOVA3D_TOKEN is not set. Create an API key at https://nova3d.xyz/settings → API Keys...
```
Server should NOT exit immediately (process stays alive for the 2 seconds).

- [ ] **Step 4: Smoke-test startup with fake token**

```bash
source .venv/bin/activate && NOVA3D_TOKEN="n3d_fake" python -m nova3d_mcp.server 2>&1 &
sleep 5 && kill %1
```

Expected stderr: auth error message pointing to `nova3d.xyz → Settings → API Keys`. Server stays running.

- [ ] **Step 5: Commit**

```bash
git add nova3d_mcp/server.py
git commit -m "feat: update mcp instructions to proactively guide users through API key setup"
```
