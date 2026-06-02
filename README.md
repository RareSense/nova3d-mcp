# nova3d-mcp

**Structured, part-aware 3D generation for AI agents.**

nova3d-mcp is an [MCP](https://modelcontextprotocol.io) server that exposes
[Nova3D](https://nova3d.xyz)'s generation pipeline as a callable tool inside
Claude Code, Cursor, and any MCP-compatible agent.

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

## Quickstart

### 1. Get an API key

Get an API key at: https://app.nova3d.xyz/api-key

```bash
export NOVA3D_TOKEN="n3d_your-api-key-here"
```

API keys never expire unless revoked. The MCP server validates your key on startup
and prints a clear error if it's missing or invalid.

### 2. Configure Your Agent

You can run `nova3d-mcp` directly using `uvx` (recommended) or by installing from source.

#### Option A: Running via PyPI (Recommended)
Add this to your agent's configuration file (e.g., `claude_desktop_config.json`):

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

#### Option B: Installing from Source
Clone the repository and install the package locally:

```bash
git clone https://github.com/RareSense/nova3d-mcp.git
cd nova3d-mcp
python3.10 -m venv .venv && source .venv/bin/activate
pip install .
```

Then add this to your agent's configuration file:

```json
{
  "mcpServers": {
    "nova3d": {
      "command": "nova3d-mcp",
      "env": {
        "NOVA3D_TOKEN": "n3d_your-api-key-here"
      }
    }
  }
}
```

### 3. Generate

Pass a prompt like this to your AI agent:

```
Generate a vending machine with separate door, glass panel, coin slot,
button grid, frame, and interior shelving.
```

The agent calls `generate_3d`. You get back:

```json
{
  "glb_url": "https://nova3d.xyz/assets/abc123.glb",
  "preview_url": "https://nova3d.xyz/preview/state-...",
  "conversation_url": "https://nova3d.xyz/chat/conv-...",
  "parts": ["door", "glass_panel", "coin_slot", "button_grid", "frame", "shelf_1", "shelf_2"],
  "joint_count": 1,
  "code_artifact": { ... },
  "workflow_id": "state-..."
}
```

- **`preview_url`** — interactive Three.js viewer with named parts, orbit controls, and part explosion. No Blender required.
- **`conversation_url`** — your editing session on nova3d.xyz. Open this to see the full generation and edit history for this asset. All subsequent `regenerate_part`, `add_part`, and `articulate_model` calls on this asset link back to the same session.

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

**Returns:** `glb_url`, `preview_url`, `conversation_url`, `parts`, `joint_count`, `code_artifact`, `model_artifact`, `workflow_id`. Pass `code_artifact` to any edit tool. Open `conversation_url` to see the full edit history for this asset on nova3d.xyz.

---

### `regenerate_part`

Regenerate one named part without rebuilding the whole asset.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `code_artifact` | object | ✓ | From prior `generate_3d` result |
| `part_type` | string | ✓ | Part name e.g. `"door"`, `"handle"` |
| `description` | string | ✓ | What the new part should look like |
| `model` | string | | `"gemini"` (default) · `"claude-sonnet"` · `"claude-opus"` · `"claude-opus-latest"` · `"gpt-5.5"` |

**Finding part names:** Open the `preview_url` from your generation — each
mesh is labeled. Use that exact name as `part_type`.

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
   → glb_url, preview_url, conversation_url, parts, code_artifact

2. Open preview_url in browser
   → see named parts, identify what needs changing
   Open conversation_url to see the full session on nova3d.xyz

3. regenerate_part(code_artifact, part_type="head", description="...")
   → updated glb_url, new preview_url, same conversation_url

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
