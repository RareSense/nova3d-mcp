# Pre-Launch Readiness — Design Spec
**Date:** 2026-05-29
**Scope:** Gaps 2.1 (server.json), 2.2 (.env.example), 3.1 (fix parts extraction), 4.2 (README install)

---

## Problem

Four small gaps block a clean launch:

1. No `server.json` — the MCP registry and PulseMCP won't list the server without it.
2. No `.env.example` — expected convention for any server with required env vars.
3. `parts` always returns `[]` for non-articulated assets — `_extract_part_names()` only reads from `joints`, which is empty on ~99% of generations.
4. README says `uvx nova3d-mcp` works today — it doesn't until the package is on PyPI.

---

## Changes

### 1. `server.json` — MCP registry manifest

New file at repo root. Required by the official MCP Registry
(`registry.modelcontextprotocol.io`). PulseMCP auto-pulls from there — no
separate submission needed.

```json
{
  "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
  "name": "io.github.raresense/nova3d-mcp",
  "title": "Nova3D",
  "description": "Structured, part-aware 3D generation for AI agents. Returns named-part GLB, preview URL, and Blender construction script.",
  "version": "0.1.0",
  "repository": {
    "url": "https://github.com/RareSense/nova3d-mcp",
    "type": "git"
  },
  "packages": [
    {
      "registryType": "pypi",
      "identifier": "nova3d-mcp",
      "transport": {
        "type": "stdio"
      },
      "env": [
        {
          "name": "NOVA3D_TOKEN",
          "description": "API key from nova3d.xyz → Settings → API Keys",
          "required": true
        }
      ]
    }
  ]
}
```

The `name` field must match the GitHub org namespace (`raresense`) for
namespace authentication to pass. The `version` field must match
`pyproject.toml` at publish time.

No tests — this is a static metadata file validated by the registry CLI at
publish time.

---

### 2. `.env.example`

New file at repo root:

```
# Nova3D MCP Server — environment variables
# Copy to .env and fill in your values

# Required: API key from nova3d.xyz → Settings → API Keys
NOVA3D_TOKEN=n3d_your-api-key-here

# Optional: override the API base URL (advanced / self-hosted only)
# NOVA3D_API_URL=https://nova3d.xyz/api
```

---

### 3. Fix `_extract_part_names()` in `nova3d_mcp/models.py`

**Current behaviour:** only extracts part names from the `joints` list. For
non-articulated assets `joints` is empty, so `parts` returns `[]`.

**New behaviour:** API-first with regex fallback.

1. If the raw result contains a top-level `parts` field (list of strings),
   use it directly. This is future-proofing for when the API returns parts
   explicitly.
2. Otherwise, regex over `code_artifact["content"]` to find all
   `.name = "..."` assignments. In Nova3D's Blender output this is always how
   mesh objects are named.
3. If neither is available (no code artifact, empty content), fall back to
   the existing joints-based extraction.

**Regex pattern:** `r'\.name\s*=\s*["\']([^"\']+)["\']'`

This matches both single and double quoted strings and tolerates whitespace
around `=`. Nova3D scripts don't emit scene-level name assignments
(`scene.name`, `collection.name`) so false positive risk is negligible.

**Signature change:** `_extract_part_names` receives `unwrapped` (the full
result dict) and `joints` (same as now). It gains access to
`unwrapped.get("parts")` for the API-first check and
`unwrapped.get("code_artifact")` for the regex fallback.

No changes to the call site in `from_api()` — the function already receives
both arguments.

**Tests:** two new unit tests in `tests/test_client.py`:

- `test_result_parsing_parts_from_code_artifact` — result with no joints but
  code artifact containing `obj.name = "body"` and `wheel.name = "wheel_fr"`;
  assert `result.parts == ["body", "wheel_fr"]`.
- `test_result_parsing_parts_api_field_takes_precedence` — result with a
  top-level `parts: ["door", "frame"]` field; assert those are returned and
  the regex is not consulted.

---

### 4. README install section

**Current:**
```markdown
### 1. Install

```bash
uvx nova3d-mcp
```

Or with pip:

```bash
pip install nova3d-mcp
```
```

**New:**
```markdown
### 1. Install

**Once on PyPI (coming soon):**
```bash
uvx nova3d-mcp
```

**From source (available now):**
```bash
git clone https://github.com/RareSense/nova3d-mcp.git
cd nova3d-mcp
python3.10 -m venv .venv && source .venv/bin/activate
pip install .
```
```

The Claude Code config example in Step 3 also needs updating to show the
`pip install` / local path alternative alongside `uvx`.

---

## Files changed

| File | Change |
|---|---|
| `server.json` | New — MCP registry manifest |
| `.env.example` | New — env var reference |
| `nova3d_mcp/models.py` | `_extract_part_names()`: API-first + regex fallback |
| `tests/test_client.py` | 2 new tests for parts extraction |
| `README.md` | Install section: add from-source path, clarify uvx status |

---

## What is not in this spec

- Publishing to PyPI — separate one-time action, documented in the todos below.
- Publishing to the MCP registry — one CLI command after PyPI is live.
- Settings UI at nova3d.xyz — separate frontend project.
- Progress reporting (gap 3.2), exponential backoff (gap 5.1), other post-launch gaps.
