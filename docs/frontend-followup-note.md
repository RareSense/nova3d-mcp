# Nova3D MCP Frontend Follow-Up Note

Backend has now responded with a concrete preferred launch architecture, and we want to align frontend against that locked direction.

## Locked Backend Direction

Preferred launch auth flow:

1. MCP starts a local loopback listener on an available port.
2. MCP opens browser to an MCP-aware Nova3D route with `state` and `port`.
3. User signs in through the normal Nova3D account flow.
4. Frontend calls `POST /mcp/session/create` with the user JWT.
5. Backend creates a short-lived one-time `session_code`.
6. Frontend redirects browser to the MCP loopback callback with `code` and original `state`.
7. MCP validates `state`, exchanges the `code` through `POST /mcp/session/exchange`, and stores the returned backend-issued `n3d_` credential locally.
8. MCP calls `GET /mcp/status` as the canonical onboarding/readiness contract.

Important clarifications:

- browser/web auth session and MCP local session are distinct
- the MCP local session is established through the one-time code exchange
- web and MCP should share one Nova3D account and one wallet
- `GET /mcp/status` is the central machine-readable state contract

## Locked Backend Contract Highlights

### `GET /mcp/status`

This is the canonical MCP state contract.

It always returns HTTP `200` with a parseable body for onboarding/readiness use cases.

Key fields:

- `authenticated`
- `identity`
- `mcp_session.established`
- `mcp_session.expires_at`
- `credits`
- `generation_ready`
- `next_action`
- `next_action_url`

Locked `next_action` enum:

- `null`
- `"sign_in"`
- `"session_expired"`
- `"purchase_credits"`
- `"service_unavailable"`

### Checkout Context

Backend preference is:

- bounded checkout context via `source: "web" | "mcp"`
- not arbitrary caller-supplied success URLs

## What We Need From Frontend Now

Given that backend direction, we need frontend to align the route flow and user-facing browser journey.

### Route / Flow Questions To Finalize

Please confirm the preferred route set and naming.

Current likely shape:

- `/mcp/connect`
- MCP-aware login completion page such as `/mcp/ready` or `/mcp/complete`
- `/mcp/no-credits`
- MCP-aware purchase success page such as `/mcp/purchase-success`
- MCP-aware handling in OAuth callback

We do not need exact names to match this note, but we do need one stable route model.

### Specific Frontend Responsibilities

We expect frontend to handle:

- MCP-aware browser entry page
- already-signed-in fast path
- MCP-aware OAuth completion path
- post-login confirmation/readiness state
- explicit zero-credit state
- checkout initiation with `source: "mcp"`
- MCP-aware purchase return page
- explicit return-to-editor guidance

### The Key Browser-State UX We Need

After login:

- show signed-in identity
- show whether MCP handoff is complete or in progress
- show whether credits are sufficient
- if funded, clearly say Nova3D is ready in the editor

If zero credits:

- clearly say the account is connected
- clearly say generation is not ready yet
- show current credits
- give primary purchase CTA

After purchase:

- confirm funding state
- give one clear instruction:
  - return to your editor
  - or close this tab and continue in your editor

## Open Frontend Decisions

Please respond with:

1. the route names you want to standardize on
2. whether `/mcp/connect` should immediately auto-progress for already-signed-in users
3. where MCP-aware OAuth completion should branch from the current callback flow
4. whether the post-login “ready” page and post-purchase “success” page should be separate or merged
5. any UI/UX constraints that would change the recommended route model

## Reference Docs

- `/home/hassan/Desktop/nova3d-mcp/docs/mcp-auth-onboarding-master-spec.md`
- `/home/hassan/Desktop/nova3d-mcp/docs/mcp-auth-onboarding-handoff-summary.md`
- `/home/hassan/Desktop/nova3d-mcp/docs/mcp-auth-onboarding-implementation-plan.md`
