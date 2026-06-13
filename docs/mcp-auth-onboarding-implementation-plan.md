# Nova3D MCP Auth And Onboarding Implementation Plan

## Purpose

This is the MCP-repo implementation plan against the currently locked cross-system contract.

It assumes:

- browser-first onboarding
- local loopback callback
- one-time backend session-code exchange
- locally stored backend-issued `n3d_` credential
- `GET /mcp/status` as the canonical onboarding/readiness contract

This plan is intentionally scoped to the MCP repo only.

## Locked External Assumptions

### Backend

Assumed backend contracts:

- `POST /mcp/session/create`
- `POST /mcp/session/exchange`
- `GET /mcp/status`

Assumed `GET /mcp/status` response semantics:

- always returns HTTP `200` with a parseable body for MCP onboarding/readiness use
- expresses machine-readable `next_action`
- distinguishes:
  - `sign_in`
  - `session_expired`
  - `purchase_credits`
  - `service_unavailable`
  - `null` meaning ready

### Frontend

Assumed frontend routing shape:

- `/mcp/connect`
- `/mcp/complete`
- `/mcp/no-credits`
- `/mcp/purchase-success`
- shared `/oauth-callback` with MCP-aware branching

The MCP should still treat backend-provided `next_action_url` as authoritative
for routing decisions where possible.

## Goals In This Repo

1. Replace API-key-first onboarding as the primary MCP flow.
2. Support login-first onboarding through browser sign-in and loopback callback.
3. Persist a local MCP session credential.
4. Use `GET /mcp/status` to drive onboarding and readiness state.
5. Surface clear user-facing messages for sign-in, no credits, expired session, and service unavailability.
6. Preserve advanced/manual fallback for environments where loopback/browser flow is unavailable.

## Non-Goals In This Repo

- Do not redesign GraphFlow generation payloads as part of this work.
- Do not add BYOK support.
- Do not redesign edit workflows beyond auth/readiness integration if not needed.
- Do not require frontend/backend implementation details to match this repo’s internal abstractions.

## Workstreams

### 1. Local Session Storage

Add a local credential store for the MCP’s backend-issued `n3d_` credential.

Requirements:

- persistent across runs
- clearable via logout
- readable for all authenticated MCP requests
- able to represent missing vs present credential state

Implementation choices left open:

- config file under user home
- existing Codex/CLI-compatible local config path
- OS keychain if desired later

Launch recommendation:

- simple file-backed storage with restrictive permissions is acceptable if secure enough for a local developer tool

### 2. Browser Login Flow

Add MCP-side login orchestration:

1. Generate random `state` nonce.
2. Start loopback listener on an available local port.
3. Open browser to the Nova3D MCP connect route with `state` and `port`.
4. Receive loopback callback containing `code` and `state`.
5. Validate `state`.
6. Exchange `code` through `POST /mcp/session/exchange`.
7. Store returned `n3d_` credential locally.
8. Call `GET /mcp/status`.

Key behaviors:

- retry a small port range or bind random available port
- detect bind failure cleanly
- timeout gracefully if browser flow never completes
- never store or expose the one-time code after exchange
- distinguish auth-completion failure from post-purchase polling behavior

### 3. Status Client

Add a dedicated client path for `GET /mcp/status`.

This should become the MCP’s source of truth for:

- whether the user is signed in
- whether the MCP local session is established
- current account identity
- current funding state
- generation readiness
- next recommended user action

The status client should not force callers to infer onboarding state from:

- generic `401`s
- `/me`
- scattered billing endpoints
- generation failures

### 4. Onboarding State Machine

Introduce an explicit MCP-side state model driven by `GET /mcp/status`.

Required states:

- not signed in
- signing in
- signed in / status unknown
- signed in / zero credits
- signed in / funded / ready
- session expired
- service unavailable
- manual fallback required

The state machine should map directly from the backend contract rather than from ad hoc error parsing.

### 5. User-Facing Messaging

Update setup and readiness messaging so the MCP says:

- sign in to Nova3D
- connected as X
- credits available Y
- buy credits before first generation
- session expired, sign in again
- service unavailable, try again later

Avoid leading with:

- `NOVA3D_TOKEN`
- API-key copy/paste
- generic auth failures during first-run setup

### 6. Manual / Advanced Fallback

Preserve an advanced/manual path for environments where the loopback flow fails.

Examples:

- browser cannot be opened
- local port bind fails
- sandbox/container restrictions

The fallback does not need to be the primary UX, but it must be clearly explained.

At minimum, the MCP should:

- detect loopback failure
- surface a clear message
- point to the advanced/manual path

### 7. Generation Preconditions

Before `generate_3d`, the MCP should consult stored session state or call `GET /mcp/status`.

Behavior:

- if `next_action == "sign_in"`: initiate or instruct sign-in
- if `next_action == "session_expired"`: instruct re-login
- if `next_action == "purchase_credits"`: do not proceed to generation; direct user to the purchase URL
- if `next_action == "service_unavailable"`: surface service outage
- if `next_action == null` and `generation_ready == true`: proceed

### 8. Logout / Session Clearing

Add MCP-side logout behavior.

Minimum launch behavior:

- clear locally stored credential
- confirm user is disconnected locally

Optional future enhancement:

- call backend revocation for the MCP-issued key if a convenient contract exists

## Concrete File-Level Plan

### `nova3d_mcp/client.py`

Add support for:

- `GET /mcp/status`
- `POST /mcp/session/exchange`

Potentially add a separate auth/onboarding client helper if keeping the existing generation client cleaner is preferable.

### `nova3d_mcp/server.py`

Add or update tooling/surfaces for:

- login
- logout
- status
- setup/help text

Update generation preflight so it consults the status contract before attempting paid generation.

### New auth/onboarding module(s)

Likely introduce a new module for:

- loopback server lifecycle
- browser launch orchestration
- state nonce generation/validation
- local credential store
- onboarding state transitions

Suggested shape:

- `nova3d_mcp/auth.py`
- `nova3d_mcp/session_store.py`
- `nova3d_mcp/loopback.py`

Exact naming is flexible.

### Tests

Add tests for:

- missing local credential
- login callback success
- state mismatch rejection
- session-code exchange success
- `GET /mcp/status` parsing for each `next_action`
- generation blocked on `purchase_credits`
- generation blocked on `session_expired`
- loopback bind failure fallback messaging
- auth completion path that reaches `/mcp/complete`
- purchase refresh path that relies on status polling after `/mcp/purchase-success`

## Suggested Tool / Surface Changes

This repo should likely evolve toward these user-visible setup surfaces:

- `nova3d_setup`
- `nova3d_status`
- `nova3d_login`
- `nova3d_logout`

Exact MCP exposure can be decided later, but the functionality should exist.

If keeping the number of MCP tools minimal is important, login/status/logout can be implemented as CLI-level commands plus a richer `nova3d_setup` tool.

## Test Strategy

### Unit Tests

- credential storage
- state nonce generation/validation
- status response parsing
- preflight decision logic

### Integration Tests

- browser login callback path with mocked backend exchange
- status-driven no-credit path
- status-driven expired-session path
- ready path allows generation

### Manual Verification

At minimum verify:

- install in local MCP client
- browser opens
- login completes
- local credential persists
- zero-credit state blocks generation cleanly
- funded state enables generation
- expired session re-prompts login
- loopback bind failure produces advanced/manual guidance

## Sequencing

### Phase 1: Contract Client

1. Add `GET /mcp/status` client and response models.
2. Add tests for all `next_action` values.

### Phase 2: Local Session Plumbing

3. Add local credential storage.
4. Add auth header injection from stored credential.

### Phase 3: Login Flow

5. Add loopback listener and browser launch orchestration.
6. Add `POST /mcp/session/exchange` client path.
7. Add end-to-end mocked login-flow tests.

### Phase 4: Setup / UX Surfaces

8. Update setup/help messaging.
9. Add login/status/logout surfaces.

### Phase 5: Generation Gating

10. Gate paid generation on `GET /mcp/status`.
11. Ensure no-credit and expired-session states are surfaced before generation.

### Phase 6: Manual Fallback

12. Add clear bind-failure/browser-failure fallback messaging.

## Risks

### Loopback Environment Risk

Some environments may not permit:

- opening a browser
- binding a local loopback port
- routing browser callback back to the MCP process

Mitigation:

- keep advanced/manual fallback
- surface bind/open failures clearly

### Contract Drift Risk

If backend changes `GET /mcp/status` shape during implementation, MCP logic could drift.

Mitigation:

- treat the backend response shape as locked
- add fixture-based tests

### Session Lifetime Risk

If backend expiry semantics change, MCP re-auth behavior may break.

Mitigation:

- rely on `session_expired` / `expires_at` from status contract
- avoid duplicating expiry logic locally

## Deliverables

This repo should ultimately deliver:

- login-first onboarding flow
- locally stored MCP session credential
- `GET /mcp/status`-driven state handling
- no-credit pre-generation blocking
- explicit expired-session handling
- advanced/manual fallback guidance
