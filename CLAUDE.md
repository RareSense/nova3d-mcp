# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An MCP server that wraps Nova3D's hosted 3D generation API as callable tools for Claude Code and other MCP-compatible agents. Users bring their own LLM provider key (Google, Anthropic, or OpenAI) and a Nova3D JWT token.

## Commands

```bash
# First-time setup — create venv and install dev dependencies
python3.10 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run tests (venv must be active)
pytest

# Run a single test
pytest tests/test_client.py::test_generate_success

# Run the server locally
python -m nova3d_mcp.server
# or after install:
nova3d-mcp

# Lint
ruff check .
```

## Package layout note

The source directory on disk is `nova3d_mcp/` (underscore), matching the Python import name. Always activate `.venv` before running tests.

## Architecture

**Three-file package:**

- `nova3d_mcp/server.py` — FastMCP server. Registers 5 tools (`generate_3d`, `regenerate_part`, `add_part`, `articulate_model`, `get_generation_status`). Each tool creates a `Nova3DClient` context manager, calls the matching method, and maps the result to a flat dict. Auth (`NOVA3D_TOKEN`) and base URL (`NOVA3D_API_URL`) are read from env inside each tool call.

- `nova3d_mcp/client.py` — Async HTTP client wrapping `httpx.AsyncClient`. Workflow pattern: readiness check → POST `/run/state/{workflow}` → poll `/status/{id}` every 3 s until terminal → GET `/result/{id}`. Transient 404/502/503/504 errors during polling are retried via `_is_recoverable()`. Auth and budget errors are never retried. Workflow IDs are microsecond timestamps (`state-{epoch_us}`).

- `nova3d_mcp/models.py` — Pydantic models. `GenerationResult.from_api()` contains all response-parsing logic — the Nova3D API response structure is nested and has multiple fallback key paths (e.g. `model_url` vs `model_artifact.url`). `WorkflowState.parse()` normalizes state strings (`"succeeded"` → `COMPLETED`, etc.) and `is_terminal` drives the polling loop.

**Data flow for a generation:**
```
tool call → _get_token() + _get_api_url()
         → Nova3DClient.__aenter__()
         → client.generate() → check_readiness() → _start_workflow() → _poll_and_collect()
         → GenerationResult.from_api(raw_dict, workflow_id)
         → tool returns flat dict to MCP caller
```

**Test setup:** `tests/test_client.py` uses `respx` to mock `httpx` at the transport level. `asyncio.sleep` is monkey-patched to `sleep(0)` inside tests to avoid real delays. The `mock_api` fixture scopes the mock to the test function with `assert_all_called=False`.

## Environment variables

| Variable | Required | Default |
|---|---|---|
| `NOVA3D_TOKEN` | Yes | — |
| `NOVA3D_API_URL` | No | `https://nova3d.xyz/api` |
