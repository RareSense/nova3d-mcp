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

### 1. Install

```bash
uvx nova3d-mcp
```

Or with pip:

```bash
pip install nova3d-mcp
```

### 2. Get an API key

Sign in at [nova3d.xyz](https://nova3d.xyz), go to **Settings → API Keys**, and create a key.

```bash
export NOVA3D_TOKEN="n3d_your-api-key-here"
```

API keys never expire unless revoked. The MCP server validates your key on startup
and prints a clear error if it's missing or invalid.

### 3. Add to Claude Code

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

### 4. Generate

```
Generate a vending machine with separate door, glass panel, coin slot,
button grid, frame, and interior shelving. Use Google Gemini with my
API key AIza...
```

The agent calls `generate_3d`. You get back:

```json
{
  "glb_url": "https://nova3d.xyz/assets/abc123.glb",
  "preview_url": "https://nova3d.xyz/preview/state-...",
  "parts": ["door", "glass_panel", "coin_slot", "button_grid", "frame", "shelf_1", "shelf_2"],
  "joint_count": 1,
  "code_artifact": { ... },
  "workflow_id": "state-..."
}
```

Open `preview_url` in your browser — interactive Three.js viewer, named parts,
orbit controls, part explosion. No Blender required to preview.

---

## Tools

### `generate_3d`

Generate a structured 3D asset from text (and optional reference image).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `prompt` | string | ✓ | Asset description. Be specific about parts. |
| `provider` | string | ✓ | `"google"` · `"anthropic"` · `"openai"` |
| `api_key` | string | ✓ | Your BYOK key for the provider |
| `llm` | string | | Model ID. Defaults to recommended per provider. |
| `image_base64` | string | | Reference image as plain base64 |
| `image_mime` | string | | e.g. `"image/jpeg"` |

**Recommended provider:** `google` with `gemini-2.0-flash` — best spatial
reasoning for complex multi-part objects.

---

### `regenerate_part`

Regenerate one named part without rebuilding the whole asset.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `code_artifact` | object | ✓ | From prior `generate_3d` result |
| `part_type` | string | ✓ | Part name e.g. `"door"`, `"handle"` |
| `description` | string | ✓ | What the new part should look like |
| `provider` | string | ✓ | LLM provider |
| `api_key` | string | ✓ | BYOK key |
| `llm` | string | | Model ID |

**Finding part names:** Open the `preview_url` from your generation — each
mesh is labeled. Use that exact name as `part_type`.

---

### `add_part`

Add a new component to an existing asset.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `code_artifact` | object | ✓ | From prior generation result |
| `description` | string | ✓ | Description of the new part and where it goes |
| `provider` | string | ✓ | LLM provider |
| `api_key` | string | ✓ | BYOK key |
| `llm` | string | | Model ID |

---

### `articulate_model`

Add joints, hinges, or rotational articulation to an existing asset.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `code_artifact` | object | ✓ | From prior generation result |
| `model_url` | string | ✓ | `glb_url` from prior generation |
| `articulation_request` | string | ✓ | What should move and how |
| `provider` | string | ✓ | LLM provider |
| `api_key` | string | ✓ | BYOK key |
| `llm` | string | | Model ID |
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
   → glb_url, preview_url, parts, code_artifact

2. Open preview_url in browser
   → see named parts, identify what needs changing

3. regenerate_part(code_artifact, part_type="head", description="...")
   → updated glb_url, new preview_url

4. articulate_model(code_artifact, model_url, "make legs rotate at hip joints")
   → glb_url with working joints
```

---

## Provider reference

| Provider | `provider` | Default `llm` | Notes |
|---|---|---|---|
| Google Gemini | `google` | `gemini-2.0-flash` | Recommended |
| Anthropic | `anthropic` | `claude-sonnet-4-20250514` | Strong reasoning |
| OpenAI | `openai` | `gpt-4o` | Widely available |

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `NOVA3D_TOKEN` | ✓ | API key from nova3d.xyz → Settings → API Keys (recommended) or session JWT |
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
