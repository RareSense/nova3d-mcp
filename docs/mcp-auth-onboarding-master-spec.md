# Nova3D MCP Auth And Onboarding Master Spec

## Goal

Design a smooth first-time Nova3D MCP experience for users in Codex, Cursor,
Claude Code, VS Code, Visual Studio, and similar MCP clients.

The intended experience is:

1. User installs the Nova3D MCP server.
2. User is prompted to sign in to Nova3D immediately or on first meaningful use.
3. Browser-based sign-in completes without requiring the user to copy an API key.
4. The MCP server stores a local Nova3D session credential.
5. The MCP server checks account identity, generation readiness, and credit status.
6. If the user has zero credits, the system routes them into a simple purchase flow
   before first generation.
7. Once funded, generation works without further auth setup.

This spec is a shared product-and-contract document. It is not a repo-specific
implementation plan.

## Scope

This spec covers:

- Nova3D MCP onboarding and auth UX
- backend support required for browser sign-in and session validation
- frontend support required for login, post-login confirmation, and no-credit purchase flow
- shared contracts and state transitions between MCP, backend, and frontend

This spec does not prescribe:

- exact file-level code changes in the Flutter or backend repos
- internal storage mechanism details beyond required behavior
- BYOK onboarding
- a full refactor of existing generation/edit workflows beyond what is needed for auth and onboarding

## Non-Goals

- Do not make raw API-key setup the primary onboarding path.
- Do not include BYOK in the launch onboarding flow.
- Do not require users to understand Nova3D backend credential mechanics.
- Do not force frontend/backend teams into a specific internal architecture where contract behavior is sufficient.

## Product Principles

- Account-first, not API-key-first.
- Browser sign-in is the primary onboarding method.
- Credit readiness should be surfaced before first paid generation failure.
- The user should understand their current state at all times:
  not signed in, signed in but unfunded, funded and ready, session expired, backend unavailable.
- The MCP server should remain compatible with local stdio installation across editors.

## Primary User Journey

### Install

1. User adds the Nova3D MCP server in their editor or agent client.
2. Installation should not require the user to fetch or paste a Nova3D API key.

### First Startup / First Use

3. The MCP server detects whether a valid local Nova3D session exists.
4. If no valid session exists, the MCP server prompts the user to sign in to Nova3D.
5. The MCP server launches a browser sign-in flow.

### Sign-In

6. The user signs in through the Nova3D web experience.
7. On success, the MCP server receives or retrieves a local session credential
   through an explicit secure handoff.
8. The MCP server stores that credential locally and securely.

The preferred launch implementation is:

1. MCP starts a local loopback HTTP listener on an available port.
2. MCP opens the browser to an MCP-aware Nova3D route with a `state` nonce and local port.
3. After browser auth, the frontend creates a short-lived one-time session code through the backend.
4. The frontend redirects the browser to the MCP loopback callback with the one-time code and original `state`.
5. MCP validates `state`, exchanges the one-time code with the backend, and receives a locally stored `n3d_` credential.

### Immediate Readiness Check

9. After sign-in, the MCP server checks:
   - account identity
   - session validity
   - current credit balance
   - MCP local-session handoff state
   - generation readiness
10. The MCP server reports a clear status to the user.

### If Credits Are Zero

11. The MCP server should not wait for first generation to fail.
12. It should tell the user that Nova3D credits are required for generation.
13. It should direct the user into a simple purchase flow.
14. After purchase, the MCP server should be able to re-check readiness cleanly.

### First Successful Generation

15. Once the user is funded and ready, `generate_3d` works without further auth setup.

### Returning User

16. Returning users should not be asked to sign in again if the local session is still valid.
17. If the session is expired or invalid, the MCP server should ask the user to sign in again.

## Alternate / Advanced Path

Raw API-key auth may continue to exist as an advanced or internal path for:

- automation
- CI
- debugging
- non-interactive environments

It is not the default onboarding path and should not dominate public docs or setup flows.

## User States

The system should treat the following as explicit user states.

### State: Not Signed In

Meaning:
- no local Nova3D session is stored
- or the stored session is missing and cannot be refreshed

Expected MCP behavior:
- prompt sign-in
- offer login action
- do not tell the user to fetch an API key

### State: Signing In

Meaning:
- browser login flow has been initiated

Expected MCP behavior:
- show that Nova3D sign-in is in progress
- provide retry/cancel guidance if completion does not occur

### State: Signed In, Status Unknown

Meaning:
- session exists
- readiness, handoff state, or credit status has not yet been fully confirmed

Expected MCP behavior:
- validate session
- fetch account identity, funding state, and MCP handoff/readiness state

### State: Signed In, Zero Credits

Meaning:
- identity is valid
- session is valid
- credits are insufficient for paid generation

Expected MCP behavior:
- clearly say generation requires Nova3D credits
- offer billing/purchase next step
- avoid waiting for generation failure to surface this

### State: Signed In, Funded, Ready

Meaning:
- identity is valid
- credits are sufficient
- backend readiness check passes

Expected MCP behavior:
- generation can proceed normally

### State: Session Expired

Meaning:
- locally stored session is no longer valid

Expected MCP behavior:
- tell the user they must sign in again
- offer a re-login path

### State: Backend Unavailable

Meaning:
- login or readiness service is temporarily unavailable

Expected MCP behavior:
- show a service-availability message
- distinguish this from invalid login or insufficient credits

## Shared UX Requirements

### Onboarding Messaging

The default user-facing setup message should describe:

- Nova3D requires a Nova3D account sign-in
- paid generation requires Nova3D credits
- sign-in happens through the browser

It should not lead with:

- raw token environment variables
- API key copy/paste instructions

### Post-Login Messaging

After login, the user should see:

- signed-in identity
- current credit state
- whether MCP local-session setup completed
- whether the system is ready to generate

Example shape:

- Connected as `user@example.com`
- Credits available: `0`
- Buy credits to start generating 3D assets

### Purchase Messaging

The no-credit state should guide the user into a minimal, intentional purchase flow.

The message should feel like:

- setup complete
- account connected
- credits required for generation

It should avoid looking like:

- a broken generation attempt
- a generic auth failure
- an API-key issue

### Return-To-Editor Messaging

The completion pages in the browser flow must give one clear next instruction.

Examples:

- Return to your editor now
- You can close this tab and continue in Codex
- Nova3D is ready in your editor

## MCP Requirements

### Required Behavior

The MCP server must:

- support browser-based Nova3D sign-in as the primary onboarding method
- store a local user session credential
- validate session state
- report signed-in identity
- report credit status
- report readiness state
- prompt the user to buy credits before first paid generation if credits are zero
- re-prompt for sign-in when the session expires

The MCP server must not assume that an existing browser session alone is enough.
It needs its own explicit authenticated local state after browser login completes.

### Suggested MCP Commands / Surfaces

The MCP product should support the equivalent of:

- `nova3d login`
- `nova3d logout`
- `nova3d status`

These may be implemented as CLI commands, MCP-exposed setup/status tools, or both.

### Setup Tooling

The MCP setup surface should evolve from API-key instructions to account-based onboarding.

The setup surface should be able to communicate:

- not signed in
- signed in as X
- MCP local session established or not
- credits available Y
- ready / not ready

### Generation Preconditions

Before `generate_3d`, the MCP server should be able to determine:

- whether the session is valid
- whether the account is funded
- whether the generation service is ready

The intent is to prevent avoidable first-generation failures caused by known lack of credits.

### Credential Storage

The MCP server must store its local session credential securely enough for a desktop developer tool.

This spec does not require a specific storage library or mechanism, but it requires:

- persistence across sessions
- ability to revoke or clear the session
- no need for the user to manually re-enter credentials every run

For launch, the preferred local credential is a backend-issued `n3d_` Nova3D key
obtained through the browser login handoff, not a browser JWT copied into local config.

### API Key Fallback

If API-key auth remains available as an advanced path, it should:

- be treated as secondary
- not dominate public onboarding docs
- not be required for ordinary users

## Backend Requirements

### Auth Flow Support

The backend must support a browser-based sign-in flow suitable for a local MCP or CLI client.

Acceptable implementation patterns include:

- redirect-based login completion
- device-code style flow
- browser login followed by local session polling or exchange

This spec does not mandate one auth-flow shape, but it does require that:

- the local MCP can initiate login
- the user can complete login in browser
- the MCP can reliably detect login completion
- the browser login can establish an explicit local MCP-authenticated session through a secure handoff

Preferred launch auth flow:

- local loopback callback
- one-time session code exchange
- backend-issued `n3d_` MCP credential persisted locally by the MCP server

### Session Model

The backend must support a session credential that the MCP can use for:

- identity lookup
- credit status lookup
- readiness checks
- generation/status/result calls

The backend team may choose whether this credential is:

- JWT-based
- refresh-token based
- opaque-token based
- derived from an existing auth/session model

This spec cares about behavior, not token format.

The backend must treat:

- browser/web auth session
- MCP local session

as related but distinct states. The browser may already know the user, but the
MCP still requires a deliberate local authenticated state.

For launch, the recommended backend session model is:

- browser/web auth for the human sign-in flow
- one-time `session_code` stored server-side with short TTL
- one-time code exchange into a local `n3d_` credential for MCP use

### Required Backend Capabilities

The backend must support the logical equivalent of:

- start login
- complete login
- establish MCP local-session handoff
- validate current session
- get current user/account identity
- get current credit balance or paid-generation funding status
- support purchase success refresh / re-check

If feasible, the backend should provide a combined MCP onboarding/readiness
status response instead of requiring the client to combine many fragmented
checks. That response should ideally cover:

- authenticated or not
- identity
- MCP handoff/session established or not
- credit balance or funded state
- generation readiness
- recommended next action

Recommended backend primitives for launch:

- `POST /mcp/session/create`
- `POST /mcp/session/exchange`
- `GET /mcp/status`

### Generation Auth

The backend must define how MCP-authenticated generation requests are authorized.

The user-facing model should be:

- the generation runs under the signed-in Nova3D account
- credits are consumed from that account

The implementation may use:

- direct session-bound auth
- scoped backend-issued token exchange
- another internal authorization model

### Readiness / Billing Awareness

The backend should make it possible for the MCP to distinguish:

- invalid/expired session
- zero credits / insufficient paid-generation funding
- service unavailable
- generation readiness false for non-billing reasons

`GET /mcp/status` is the canonical MCP state contract and should return a
machine-readable body even for unauthenticated and expired-session states.

### Purchase State Refresh

The backend should make it easy for the MCP to re-check readiness after the user completes a purchase.

This can be implemented by:

- explicit re-check endpoint use
- polling
- callback-linked flow

The spec does not mandate the mechanism.

The backend should also support MCP-aware completion handling for:

- OAuth/login completion
- Stripe/purchase completion

## Frontend Requirements

### MCP-Aware Login Flow

The Nova3D frontend should support a login journey that works well when initiated by a local MCP process.

It should clearly communicate:

- that the user is connecting Nova3D to their editor/agent
- when login is complete
- what the user should do next

The recommended approach is an MCP-aware route flow inside the existing Nova3D
frontend, not a separate site and not a separate auth system.

The preferred route model currently is:

- `/mcp/connect`
- `/mcp/complete`
- `/mcp/no-credits`
- `/mcp/purchase-success`

The current frontend recommendation is:

- keep `/oauth-callback` as the shared OAuth landing route
- branch into MCP mode there when auth originated from `/mcp/connect`
- keep MCP pages outside the normal authenticated app shell so they can manage transitional states cleanly

### Post-Login Confirmation

After browser login, the frontend should support a clear completion state that can tell the user:

- you are signed in
- the editor connection can continue
- whether MCP session handoff is ready
- whether credits are sufficient

If feasible, this page should also help the MCP detect completion cleanly.

### No-Credits Experience

The frontend should support an MCP-aware no-credits state that makes purchase the obvious next step.

It should clearly communicate:

- your account is connected
- you need credits to generate
- here is the purchase action

The no-credit state should show, where appropriate:

- account email
- current credits
- short explanation that credits are account-wide and required before generation

### Purchase Flow

The Stripe purchase path should be optimized for first-time MCP users where possible.

The desired experience is:

- minimal confusion
- minimal navigation detours
- clear return path back to the editor flow

Use the same Nova3D credit packages and the same shared wallet unless there is
some hard technical reason not to. The preferred launch model is one shared
account wallet across web and MCP, not channel-specific balances.

Checkout initiation should use a bounded MCP/web source signal, not arbitrary
caller-provided success URLs.

### Post-Purchase Confirmation

After successful purchase, the frontend should support a confirmation state that allows the MCP to re-check readiness smoothly.

The page should ideally communicate:

- Nova3D is ready in your editor
- updated credit balance
- clear instruction to return to the editor or close the tab

### Deep Links / Polling / Completion Strategy

The frontend and backend teams should jointly decide the cleanest completion mechanism for:

- login completion
- purchase completion

This spec does not mandate whether that is:

- polling
- callback URL
- local loopback redirect
- browser message relay

The frontend and backend should aim to avoid brittle fragmented polling if a
combined onboarding/readiness status flow is feasible.

## Shared Contracts

The following cross-system contracts need to exist, whether formalized as HTTP endpoints, app routes, or another integration shape.

### Contract: Login Initiation

MCP must be able to initiate a browser login flow.

### Contract: Login Completion

MCP must be able to determine that login has completed successfully or failed.

### Contract: MCP Local-Session Handoff

MCP must be able to establish its own authenticated local session after browser
login completes.

### Contract: Session Validation

MCP must be able to validate whether the current local session is valid.

### Contract: Identity Lookup

MCP must be able to obtain account identity for user-facing status messaging.

### Contract: Credit Status

MCP must be able to determine whether the user is funded for paid generation.

The preferred model is a shared Nova3D account wallet across app and MCP.

### Contract: Purchase Refresh

MCP must be able to determine whether a purchase has changed the user's funded state.

### Contract: Generation Authorization

Generation requests must run under the signed-in Nova3D account without requiring raw API-key setup.

### Contract: Canonical MCP Status

`GET /mcp/status` is the canonical state contract for MCP onboarding and readiness.

Preferred launch behavior:

- always return `200` with a parseable state body
- encode unauthenticated, expired-session, zero-credit, and service-unavailable
  states in the response body instead of making the MCP infer them from generic auth failures

Preferred response shape:

```json
{
  "authenticated": true,
  "identity": {
    "user_id": "...",
    "email": "user@example.com",
    "tenant_id": "ten_..."
  },
  "mcp_session": {
    "established": true,
    "expires_at": "2026-09-10T14:32:00Z"
  },
  "credits": {
    "balance": 350,
    "reserved": 50,
    "available": 300,
    "funded": true
  },
  "generation_ready": true,
  "next_action": null,
  "next_action_url": null
}
```

Preferred `next_action` enum:

- `null`
- `"sign_in"`
- `"session_expired"`
- `"purchase_credits"`
- `"service_unavailable"`

## Acceptance Criteria

The end-to-end system is acceptable when all of the following are true.

### Install And Sign-In

- A new user can install Nova3D MCP without obtaining a raw API key.
- A new user is prompted to sign in through the browser.
- A signed-in session persists locally for later use.
- Browser sign-in completion is not treated as sufficient until MCP local-session handoff is complete.
- MCP can derive all onboarding and readiness state from `GET /mcp/status`.

### No-Credits Path

- A signed-in but unfunded user is told they need credits before first paid generation.
- The system directs them to a purchase path without requiring a failed generation first.
- After purchase, the MCP can re-check and recognize funded state.
- The browser purchase flow gives explicit return-to-editor guidance.

### Funded Path

- A signed-in funded user can generate successfully without any manual token setup.

### Expired Session

- An expired session produces a re-login prompt, not a confusing generation failure.

### Availability Failures

- Service unavailability is distinguishable from auth failure and billing failure.

## Regression Strategy

Regression prevention should be layered rather than purely unit-test-driven.

### Contract Tests

Test the cross-system contracts for:

- login completion
- session validation
- identity lookup
- credit status lookup
- purchase refresh

### Unit Tests

Each repo should cover its own internal auth/session logic.

### Integration Tests

Recommended integration scenarios:

- first-time login success
- first-time login abandoned/failed
- browser login success but MCP local-session handoff incomplete/failing
- signed-in zero-credit state
- purchase then readiness refresh
- funded generation path
- expired session path
- loopback listener bind failure with manual fallback guidance

### Manual Acceptance Checklist

A shared manual checklist should cover:

- Codex
- Cursor
- Claude Code
- VS Code
- Visual Studio

At minimum, validate:

- browser opens
- sign-in completes
- status becomes connected
- zero-credit message appears when appropriate
- purchase path works
- post-purchase generation works

## Recommended Team Workflow

This master spec should be shared with:

- MCP owner
- backend owner(s)
- frontend owner(s)

Recommended process:

1. Agree on the desired user journey and state machine.
2. Agree on the minimum required shared contracts.
3. Let each owning team derive its own implementation plan from this spec.
4. Re-converge on acceptance criteria and test coverage.

The frontend and backend teams should use their own repo knowledge to design implementations that satisfy this spec without being forced into dogmatic internal structures.

## Open Questions

These must be resolved before implementation is locked.

1. What exact purchase completion detection mechanism should the MCP use for launch?
   Current backend recommendation is polling against `GET /mcp/status` after purchase initiation. Confirm whether that is the final launch behavior.

2. What should frontend and MCP do if browser auth succeeds but loopback handoff is delayed or cannot complete immediately?
   Clarify whether any polling-style fallback applies to auth completion, or whether polling is purchase-refresh-only and auth handoff failure should route users into explicit retry/manual guidance.

3. Should sign-in be prompted immediately at install/startup, or first time the server is actually invoked by the client?
   Product preference currently leans toward immediate or near-immediate prompting.

4. How prominently, if at all, should the advanced API-key path remain documented?

## Rollout Recommendation

Recommended rollout order:

1. Finalize shared contracts and auth-flow choice.
2. Backend implements login/session/credit-status capabilities.
3. Frontend implements MCP-aware login and no-credit purchase experience.
4. MCP server implements login-first onboarding and status checks.
5. Cross-system integration testing.
6. Editor/client manual verification.

## Summary

The intended launch experience is:

- install Nova3D MCP
- sign in through browser
- immediately understand whether the account is ready
- if no credits, purchase credits before first generation
- once funded, generate without token plumbing

This is the intended product shape for launch. API-key-first setup is not.
