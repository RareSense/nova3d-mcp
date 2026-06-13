# Nova3D MCP Auth And Onboarding Handoff Summary

## What This Is

We are preparing the first public launch of the Nova3D MCP server.

A current version of the MCP server already exists. It works like a typical developer integration:

- user installs the MCP server locally
- user is told to fetch a Nova3D API key
- user puts that key into MCP config
- user only discovers missing credits later when generation fails

We do **not** want to launch with that experience.

## What We Want Instead

We want the MCP onboarding flow to feel like a normal product, not a backend integration.

Target experience:

1. User installs Nova3D MCP in Codex, Cursor, Claude Code, VS Code, Visual Studio, or a similar client.
2. User is prompted to sign in to Nova3D through the browser.
3. The MCP server establishes and stores its own local Nova3D session after sign-in.
4. The MCP server checks:
   - who the user is
   - whether the session is valid
   - whether MCP local-session handoff completed
   - whether they have credits
   - whether generation is ready
5. If the user has zero credits, they are told that clearly before first generation.
6. The user is routed into a simple purchase flow.
7. After purchase, the MCP server re-checks readiness.
8. Once funded, the user can generate normally.

The intended public onboarding path is **account sign-in**, not **manual API key setup**.

Preferred launch auth model:

- browser sign-in
- local loopback callback
- one-time backend session-code exchange
- MCP stores a backend-issued `n3d_` credential locally
- MCP uses `GET /mcp/status` as the canonical onboarding/readiness state contract

## Why We Are Doing This

The MCP server is meant for broad editor/agent use.

If users must:

- learn what an API key is
- fetch a token manually
- paste it into MCP config
- then separately discover they also need credits

the experience is too fragile and high-friction for launch.

We want:

- browser sign-in
- early credit awareness
- minimal confusion
- minimal “failed generation as onboarding”

## Important Product Decisions Already Made

- BYOK is out of scope for this launch flow.
- API keys should not be the primary onboarding path.
- We are optimizing for the smoothest first-time user experience.
- We do not need to preserve old onboarding for an existing user base.

## What We Need From Backend

We need backend support for a local MCP/CLI-style sign-in flow.

At minimum, the MCP needs to be able to:

- initiate login in the browser
- detect when login has completed
- establish an explicit secure MCP local-session handoff after browser auth
- store a local session credential
- validate that session later
- fetch account identity
- fetch credit/funding status
- tell whether the account is ready for paid generation
- re-check status after a purchase

If feasible, we want a combined MCP onboarding/readiness status response instead
of forcing the client to stitch together many fragmented checks.

Backend has now proposed that this combined state contract should be `GET /mcp/status`,
and that it should always return a parseable body rather than a generic 401 for
MCP onboarding/readiness use cases.

The backend team does **not** need to accept a prescribed internal design.
We need them to help define the cleanest workable contract.

Open backend design space includes:

- the backend-preferred launch flow is local loopback + one-time session-code exchange
- stored local MCP credential is a backend-issued `n3d_` key
- API key internals remain hidden from the ordinary user-facing flow

We care about the behavior more than the exact token format.

## What We Need From Frontend

We need the web/client side to support an MCP-aware auth and purchase journey.

At minimum, the frontend should help support:

- a browser login flow initiated by MCP
- a clear “you are now signed in” completion state
- a clear “MCP session handoff complete” state or checkpoint
- a clear “your account is connected but you have 0 credits” state
- a simple purchase path for first-time MCP users
- a useful post-purchase confirmation state

The frontend should assume that these users may have come from an editor and may not know Nova3D’s billing/auth model yet.

We want the frontend experience to explain:

- your account is connected
- credits are required for generation
- here is the next action
- then return to your editor

We also expect the frontend flow to use one shared Nova3D account and one shared
wallet, not separate “web” and “MCP” balances.

Current frontend recommendation is to standardize on:

- `/mcp/connect`
- `/mcp/complete`
- `/mcp/no-credits`
- `/mcp/purchase-success`

with MCP-aware branching from the shared `/oauth-callback` route.

## What We Need From Both Teams

We need agreement on the shared user journey and shared contracts.

We do **not** want to dictate repo-level implementation details.

We do want all teams aligned on:

- how login is initiated
- how login completion is detected
- how browser auth establishes MCP local authenticated state
- how the MCP loopback callback and one-time code exchange complete
- how the MCP learns account identity
- how the MCP learns credit state
- how the MCP detects purchase completion or purchase state refresh
- how auth failures differ from no-credit failures

## What The MCP Team Will Handle

On the MCP side, we will handle:

- login-first onboarding behavior
- local session storage
- user-facing status/setup messages inside the MCP flow
- readiness checks before generation
- generation behavior once the backend/frontend contracts exist

## What We Are Asking For Right Now

Please read the master spec and respond with:

1. whether the target experience is sound
2. what auth/purchase completion flow you think is most practical in your repo
3. what contracts/endpoints/pages you think are needed
4. what constraints or pitfalls we should account for before implementation

## Master Spec

Full shared spec:

[mcp-auth-onboarding-master-spec.md](/home/hassan/Desktop/nova3d-mcp/docs/mcp-auth-onboarding-master-spec.md)
