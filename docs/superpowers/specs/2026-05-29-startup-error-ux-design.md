# Startup Error UX — Design Spec

**Date:** 2026-05-29  
**Status:** Approved

## Problem

When `NOVA3D_TOKEN` is missing or invalid, the server calls `sys.exit(1)` at startup. Claude Code marks the server as `✘ failed` and the helpful error message is buried in debug logs. Users have no actionable path forward from the conversation.

## Goal

Surface auth errors directly in the Claude Code conversation so users know exactly what to do without digging through logs.

## Design

### 1. Module-level error flag (`server.py`)

Add a single module-level variable to capture startup validation failures:

```python
_startup_error: Optional[str] = None
```

### 2. `_validate_startup()` — store instead of exit

Remove `sys.exit(1)` from all branches. Store the user-facing error message in `_startup_error` instead. Stderr logging stays (useful for `claude --debug`). Server always reaches `mcp.run()`.

Error cases covered:
- `NOVA3D_TOKEN` not set → store "...Create an API key at nova3d.xyz/settings → API Keys..."
- 401 invalid/revoked key → store the code-specific message from `_auth_message_for_code`
- Network error reaching `/me` → store "Could not reach Nova3D to verify token..."

### 3. Updated `mcp` instructions

Add proactive setup guidance to the `instructions` string passed to `FastMCP`. Tells Claude: if `NOVA3D_TOKEN` is not configured, guide the user to `nova3d.xyz/settings → API Keys` and provide the one-line install command before attempting any tool call.

This fires when the server first connects — before the user hits any tool error.

### 4. Guard in all 5 tools

Add at the top of `generate_3d`, `regenerate_part`, `add_part`, `articulate_model`, and `get_generation_status`:

```python
if _startup_error:
    return {"failed": True, "error_message": _startup_error}
```

This is purely additive — existing tool logic is unchanged.

### 5. Tests (`tests/test_server.py`)

Three new test cases:

| Scenario | Setup | Expected |
|---|---|---|
| Missing token | set `server._startup_error` to missing-token message | each tool returns `{"failed": True, "error_message": ...}` |
| Invalid token | set `server._startup_error` to invalid-key message | each tool returns `{"failed": True, "error_message": ...}` |
| No error | `server._startup_error = None` | tools proceed normally (regression guard) |

Tests directly set the module-level flag — no need to mock HTTP or call `_validate_startup()`.

## User-facing flow after this change

```
User installs with wrong/missing token
  → server starts (no exit)
  → Claude Code shows ✔ connected
  → User: "generate me a chair"
  → Claude (from instructions): "You need a Nova3D API key first.
     Get one at nova3d.xyz/settings → API Keys, then run:
     claude mcp add nova3d -e NOVA3D_TOKEN=n3d_your-key -- uvx nova3d-mcp"
  → If user calls tool anyway → {"failed": true, "error_message": "...nova3d.xyz/settings..."}
```

## Scope

**In scope:** `server.py` only — error flag, startup function, instructions string, tool guards.  
**Out of scope:** `client.py`, `models.py`, mid-session token revocation (separate concern).  
**Existing tests:** Unaffected — they instantiate `Nova3DClient` directly and never call `_validate_startup()`.
