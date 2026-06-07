# nova3d-mcp

**Structured, part-aware 3D generation for AI agents.**

nova3d-mcp is an [MCP](https://modelcontextprotocol.io) server that exposes
[Nova3D](https://nova3d.xyz)'s generation pipeline as a callable tool inside
Codex, Cursor, VS Code, Visual Studio, Claude Code, and other MCP-compatible agents.

One tool call. A washing machine comes back with named drum, door, control
panel, and hose connectors — separately editable, not fused into a blob.

---

## Why Nova3D

Every major AI 3D generator today produces **mesh blobs** — a single fused
object that looks plausible in a render and collapses the moment you try to
edit, rig, or pipeline it.

Nova3D is different. Instead of diffusion → mesh, it runs:

```
prompt / image
      ↓
LLM writes Blender Python construction code
      ↓
headless Blender executes + validates + repairs
      ↓
structured GLB — named parts, intact hierarchy, real joints
```

The result is a 3D asset that **survives contact with real workflows**: game
engines, configurators, robotics simulations, AR scenes. Parts have names.
Hierarchy is intact. Joints are real. You can change one component without
regenerating everything.

---

## Supported clients

| Client | Status | Install path | Preview path |
|---|---|---|---|
| Codex | Supported | `codex mcp add` or Codex MCP config | Browser `preview_url` |
| Cursor | Supported | `.cursor/mcp.json` or `~/.cursor/mcp.json` | Browser `preview_url` |
| VS Code | Supported | `.vscode/mcp.json`, MCP: Add Server, or `code --add-mcp` | Browser `preview_url` |
| Visual Studio | Supported | `.mcp.json` or Visual Studio MCP UI | Browser `preview_url` |
| Claude Code | Supported | `claude mcp add` | Browser `preview_url` |

Nova3D runs from your MCP client, but model inspection happens through the
hosted browser viewer returned as `preview_url`. This repository does not
currently ship an embedded IDE-native 3D viewport.

---

## Quickstart

### 1. Get an API key

Get an API key at: https://app.nova3d.xyz/api-key

```bash
export NOVA3D_TOKEN="n3d_your-api-key-here"
```

API keys never expire unless revoked. The MCP server validates your key on startup
and prints a clear error if it's missing or invalid.

### 2. Install in your MCP client

#### Codex

```bash
codex mcp add nova3d --env NOVA3D_TOKEN=n3d_your-api-key-here -- uvx nova3d-mcp
```

Codex also supports MCP configuration through `~/.codex/config.toml`. If you
prefer config files over the CLI, use Codex's MCP config surface and point it
at the same stdio command: `uvx nova3d-mcp`.

#### Claude Code

```bash
claude mcp add nova3d -e NOVA3D_TOKEN=n3d_your-api-key-here -- uvx nova3d-mcp
```

#### Cursor

Create `.cursor/mcp.json` in your project, or `~/.cursor/mcp.json` for a global
install:

```json
{
  "mcpServers": {
    "nova3d": {
      "command": "uvx",
      "args": ["nova3d-mcp"],
      "env": {
        "NOVA3D_TOKEN": "n3d_your-api-key-here"
      }
    }
  }
}
```

#### VS Code

Option A: add the server from the command line:

```bash
code --add-mcp "{\"name\":\"nova3d\",\"command\":\"uvx\",\"args\":[\"nova3d-mcp\"],\"env\":{\"NOVA3D_TOKEN\":\"n3d_your-api-key-here\"}}"
```

Option B: create `.vscode/mcp.json` in your workspace:

```json
{
  "servers": {
    "nova3d": {
      "command": "uvx",
      "args": ["nova3d-mcp"],
      "env": {
        "NOVA3D_TOKEN": "n3d_your-api-key-here"
      }
    }
  }
}
```

You can also use `MCP: Add Server` from the Command Palette.

#### Visual Studio

Create `<SOLUTIONDIR>/.mcp.json` or `%USERPROFILE%/.mcp.json`:

```json
{
  "servers": {
    "nova3d": {
      "command": "uvx",
      "args": ["nova3d-mcp"],
      "env": {
        "NOVA3D_TOKEN": "n3d_your-api-key-here"
      }
    }
  }
}
```

You can also add the server from the Visual Studio MCP UI by providing the
stdio command `uvx` with args `["nova3d-mcp"]` and the `NOVA3D_TOKEN`
environment variable.

### 3. Generate

If you prefer to install from source instead of `uvx`, clone the repository and
install the package locally:

```bash
git clone https://github.com/RareSense/nova3d-mcp.git
cd nova3d-mcp
python3.10 -m venv .venv && source .venv/bin/activate
pip install .
```

Then replace `uvx nova3d-mcp` in the client examples above with the local
`nova3d-mcp` executable from your environment.

Pass a prompt like this to your AI agent:

```
Generate a vending machine with separate door, glass panel, coin slot,
button grid, frame, and interior shelving.
```

The agent calls `generate_3d`. You get back:

```json
{
  "glb_url": "https://nova3d.xyz/assets/abc123.glb",
  "conversation_url": "https://app.nova3d.xyz/chat/conv-...",
  "parts": ["door", "glass_panel", "coin_slot", "button_grid", "frame", "shelf_1", "shelf_2"],
  "joint_count": 1,
  "code_artifact": { ... },
  "workflow_id": "state-..."
}
```

- **`conversation_url`** — your editing session in the Nova3D app, with the generated model and edit history already hydrated. All subsequent `regenerate_part`, `add_part`, and `articulate_model` calls on this asset link back to the same session.

---

## Preview and configuration notes

- `preview_url` is the standard supported way to inspect generated assets today.
- `conversation_url` opens the full edit session on nova3d.xyz.
- Keep secrets out of checked-in workspace config when possible. Prefer
  per-user configuration files or client-managed environment variables.
- If your editor supports source-controlled MCP config, commit the server entry
  and inject `NOVA3D_TOKEN` per-user.

---

## Troubleshooting

| Problem | What to check |
|---|---|
| `NOVA3D_TOKEN is not set` | Add `NOVA3D_TOKEN` to your MCP server environment and restart the client |
| Auth failure on startup | Confirm the key at https://app.nova3d.xyz/api-key |
| `uvx` not found | Install `uv` or use a local `nova3d-mcp` executable from a virtualenv |
| No 3D preview inside the editor | Open the returned `preview_url` in the browser; that is the supported preview path |

---

## Tools

### `generate_3d`

Generate a structured 3D asset from text (and optional reference image).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `prompt` | string | ✓ | Asset description. Be specific about parts. |
| `model` | string | | `"gemini"` (default) · `"claude-sonnet"` · `"claude-opus"` · `"claude-opus-latest"` · `"gpt-5.5"` |
| `image_base64` | string | | Reference image as plain base64 |
| `image_mime` | string | | e.g. `"image/jpeg"` |

**Returns:** `glb_url`, `conversation_url`, `parts`, `joint_count`, `code_artifact`, `model_artifact`, `workflow_id`. Pass `code_artifact` to any edit tool. Open `conversation_url` to see the full edit history for this asset in the Nova3D app.

---

### `regenerate_part`

Regenerate one named part without rebuilding the whole asset.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `code_artifact` | object | ✓ | From prior `generate_3d` result |
| `part_type` | string | ✓ | Part name e.g. `"door"`, `"handle"` |
| `description` | string | ✓ | What the new part should look like |
| `model` | string | | `"gemini"` (default) · `"claude-sonnet"` · `"claude-opus"` · `"claude-opus-latest"` · `"gpt-5.5"` |

**Finding part names:** Open the `conversation_url` from your generation and
inspect the model viewer — each mesh is labeled. Use that exact name as
`part_type`.

---

### `add_part`

Add a new component to an existing asset.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `code_artifact` | object | ✓ | From prior generation result |
| `description` | string | ✓ | Description of the new part and where it goes |
| `model` | string | | `"gemini"` (default) · `"claude-sonnet"` · `"claude-opus"` · `"claude-opus-latest"` · `"gpt-5.5"` |

---

### `articulate_model`

Add joints, hinges, or rotational articulation to an existing asset.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `code_artifact` | object | ✓ | From prior generation result |
| `articulation_request` | string | ✓ | What should move and how |
| `model_url` | string | | `glb_url` from prior generation. Provide this or `model_artifact`. |
| `model_artifact` | object | | `model_artifact` from prior generation. Provide this or `model_url`. |
| `model` | string | | `"gemini"` (default) · `"claude-sonnet"` · `"claude-opus"` · `"claude-opus-latest"` · `"gpt-5.5"` |
| `selected_meshes` | list | | Specific mesh names to articulate |

---

### `get_generation_status`

Check the status of a running workflow by ID.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `workflow_id` | string | ✓ | From any prior generation tool |

---

## Typical workflow

```
1. generate_3d("robot dog with four legs, head, torso, and tail")
   → glb_url, conversation_url, parts, code_artifact

2. Open conversation_url in browser
   → see named parts, identify what needs changing

3. regenerate_part(code_artifact, part_type="head", description="...")
   → updated glb_url, same conversation_url

4. add_part(code_artifact, description="a wagging tail with three segments")
   → updated glb_url, parts list now includes new tail segments

5. articulate_model(code_artifact, model_url, "make legs rotate at hip joints")
   → glb_url with working joints
```

All edit tools accept the `code_artifact` from any prior result and return an updated one. Always pass the most recent `code_artifact` forward — it carries the session state that links your edits together.

---

## Model reference

| `model` value | Provider | Notes |
|---|---|---|
| `"gemini"` *(default)* | Google Gemini | Recommended for spatial reasoning |
| `"claude-sonnet"` | Anthropic | Strong reasoning |
| `"claude-opus"` | Anthropic | Most capable Anthropic model |
| `"claude-opus-latest"` | Anthropic | Latest Opus version |
| `"gpt-5.5"` | OpenAI | Latest GPT model |

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `NOVA3D_TOKEN` | ✓ | API key from https://app.nova3d.xyz/api-key (recommended) or session JWT |
| `NOVA3D_API_URL` | | Override API base URL (default: `https://nova3d.xyz/api`) |
| `NOVA3D_APP_URL` | | Override app URL for conversation links (default: `https://app.nova3d.xyz`) |

---

## How it differs from blender-mcp

[blender-mcp](https://github.com/ahujasid/blender-mcp) (21.9k ★) gives AI
agents a remote control for a **locally running Blender instance**. It requires
Blender installed, produces unstructured output, and inherits all the bpy
hallucination problems of raw LLM → Blender code generation.

nova3d-mcp is different in kind:

| | blender-mcp | nova3d-mcp |
|---|---|---|
| Blender required | Yes | No |
| Output | Unstructured scene | Named, hierarchical GLB |
| Validation | None | Server-side repair loop |
| Part awareness | No | Yes — named, addressable |
| Joints | Manual scripting | First-class output |
| Hosted backend | No | Yes |

---

## Contributing

Issues, PRs, and workflow feedback welcome.
[github.com/RareSense/nova3d-mcp](https://github.com/RareSense/nova3d-mcp)

Community Discord: [discord.gg/QEH8mzcwdR](https://discord.gg/QEH8mzcwdR)

---

## License

MIT — see [LICENSE](LICENSE)
