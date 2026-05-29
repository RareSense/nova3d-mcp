# API Key Integration — MCP Server Design
**Date:** 2026-05-28
**Scope:** Gap 1.1 (auth), Gap 1.2 (__main__.py), proactive billing signals in tool responses

---

## Problem

`NOVA3D_TOKEN` currently expects a session JWT that expires after ~1 hour.
A user who sets it as an environment variable gets silent 401s hours later with
no recovery path that doesn't involve copying a new JWT from a browser session.
The backend now issues long-lived `n3d_` API keys. This spec integrates them
into the MCP server.

---

## What the Backend Built

Full spec at:
`/home/hassan/Desktop/Nova3D_Graphflow/docs/superpowers/specs/2026-05-28-nova3d-api-keys-design.md`

**Key facts:**
- Keys are 47-char strings starting with `n3d_`. Never expire unless revoked.
- Used identically to JWTs: `Authorization: Bearer n3d_<key>`.
- `GET /api/me` — accepts any valid credential (JWT or `n3d_` key). Returns
  `{user_id, email, available_credits, tenant_id}`. Use for startup validation.
- Management endpoints (`POST/GET/DELETE /api/api-keys`) are JWT-only.
- Users create keys at `nova3d.xyz/settings → API Keys` (UI in progress).

**Deviation from original spec — 401 error shape:**
The backend wraps error details in `detail`, not flat:
```json
{ "detail": { "code": "api_key_revoked", "message": "..." } }
```
Not:
```json
{ "code": "api_key_revoked", "message": "..." }
```
This affects `_handle_response()` in `client.py`.

**Billing signals available from generation results:**
- `result.provider` — which LLM provider was used. Already surfaced.
- `result.api_key_source` — `"request"` (user's BYOK key used) / `"server"` /
  `"server_fallback"`. Not currently surfaced. Worth adding.
- `result.cost` — **do not surface.** Unit is unverified (claimed USD, doubted).
  Nova3D credits are not currently billed (`cost_per_call: 0` for all tools).
  Revisit when billing goes live.

---

## Changes

### 1. `nova3d_mcp/client.py` — `_handle_response()`

**Current behaviour on 401:** raises `Nova3DAuthError` with a generic message.

**New behaviour:** parse `detail.code` from the response body and use the
backend's own message. Handle two cases:

```python
if resp.status_code == 401:
    code, message = _parse_auth_error(resp)
    raise Nova3DAuthError(message, status_code=401)
```

`_parse_auth_error(resp)` logic:
1. Try to parse JSON body.
2. Look for `body["detail"]["code"]` and `body["detail"]["message"]`.
3. If `detail` is a string (non-API-key 401s from FastAPI), use it as the
   message with code `None`.
4. If JSON parse fails, fall back to generic message.

Error codes and messages from the backend:

| `code` | Message to surface |
|---|---|
| `api_key_revoked` | `"Your NOVA3D_TOKEN has been revoked. Create a new key at nova3d.xyz → Settings → API Keys."` |
| `invalid_api_key` | `"Your NOVA3D_TOKEN is invalid. Check or create a key at nova3d.xyz → Settings → API Keys."` |
| anything else / missing | `"Nova3D authentication failed. Check your NOVA3D_TOKEN at nova3d.xyz → Settings → API Keys."` |

---

### 2. `nova3d_mcp/server.py` — Startup validation

**Mechanism:** `main()` calls `asyncio.run(_validate_startup())` before
`mcp.run()`. Hard failure — exits before any MCP tools are registered.

**`_validate_startup()` logic:**
1. Check `NOVA3D_TOKEN` env var. If missing or empty: print setup instructions
   and `sys.exit(1)`.
2. Call `GET /api/me` via a short-lived `Nova3DClient`.
3. On 200: print `✓ Nova3D authenticated: {email}` and return.
4. On 401: parse `detail.code`, print the specific error message (same messages
   as above), and `sys.exit(1)`.
5. On network error / timeout: print `"Could not reach Nova3D to verify token.
   Check your connection and try again."` and `sys.exit(1)`.

**Missing token message:**
```
Nova3D: NOVA3D_TOKEN is not set.
Create an API key at https://nova3d.xyz/settings → API Keys,
then set it as NOVA3D_TOKEN in your MCP config and restart.
```

**Success message:**
```
✓ Nova3D authenticated: hassan@raresense.so
```

No credits shown at startup — `available_credits` is always 0 for BYOK users
and currently always 0 for credits users too (`cost_per_call: 0`). Revisit
when billing goes live.

---

### 3. Tool responses — add `api_key_source`

Add `api_key_source` to the return dict of all four generation tools:
`generate_3d`, `regenerate_part`, `add_part`, `articulate_model`.

This field is already present in the raw result from the generation service.
`GenerationResult` in `models.py` needs a new optional field; the tool handler
passes it through.

Value is one of `"request"` (user's own BYOK key was used), `"server"`,
`"server_fallback"`, or `None` if absent.

This is low-cost and lets users/agents know whether their key was actually used.

---

### 4. `nova3d_mcp/__main__.py` — new file (Gap 1.2)

One line:
```python
from nova3d_mcp.server import main; main()
```

Enables `python -m nova3d_mcp`.

---

### 5. `README.md` — auth setup update

Replace the JWT setup section with API key instructions:

- Step 2 becomes: *"Get your API key at nova3d.xyz → Settings → API Keys"*
- `NOVA3D_TOKEN` is documented as accepting an `n3d_` API key (recommended)
  or a session JWT (still works, not recommended — expires).
- Add a note that the MCP server validates the token on startup and prints a
  clear error if it's missing or invalid.

---

## What Is Not In This Spec

- `result.cost` — not surfaced. Unit unverified. Revisit when billing goes live.
- Nova3D credits consumed per run — `actual_cost` is not in the result payload
  and requires a separate backend call. Not worth it while `cost_per_call: 0`.
- BYOK $ remaining — providers don't expose balance APIs. Not achievable.
- Token refresh / automatic JWT renewal — API keys replace the need.

---

## Files Changed

| File | Change |
|---|---|
| `nova3d_mcp/client.py` | `_handle_response()`: parse `detail.code` on 401 |
| `nova3d_mcp/server.py` | `main()`: add `asyncio.run(_validate_startup())` before `mcp.run()` |
| `nova3d_mcp/models.py` | `GenerationResult`: add optional `api_key_source` field |
| `nova3d_mcp/server.py` | All four tool handlers: include `api_key_source` in return dict |
| `nova3d_mcp/__main__.py` | New file, one line |
| `README.md` | Auth setup section: JWT → API key instructions |
