# Pre-Launch Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the four gaps that block a clean launch: parts always returning empty, missing MCP registry manifest, missing .env.example, and a README install section that implies `uvx` works before PyPI.

**Architecture:** One code change with tests (`_extract_part_names` in `models.py`), two new static files (`server.json`, `.env.example`), and one README edit. No new dependencies. The code change is the only part requiring TDD.

**Tech Stack:** Python 3.10+, `re` stdlib (new import in models.py), pytest, respx

---

## File Map

| File | Change |
|---|---|
| `nova3d_mcp/models.py` | Add `import re`; rewrite `_extract_part_names()` |
| `tests/test_client.py` | 2 new tests for parts extraction |
| `server.json` | New — MCP registry manifest |
| `.env.example` | New — env var reference |
| `README.md` | Update `### 1. Install` and `### 3. Add to Claude Code` |

---

## Task 1: Fix `_extract_part_names()` in `models.py`

**Files:**
- Modify: `nova3d_mcp/models.py` (lines 275–285: `_extract_part_names`, plus add `import re` at line 10)
- Test: `tests/test_client.py`

**Context:** The current function only reads from `joints`. Non-articulated assets (the majority) have no joints, so `parts` always returns `[]`. The fix adds two fallback layers: check the API response for an explicit `parts` field first (future-proofing), then regex-scan `code_artifact.content` for `.name = "..."` assignments (which is how Nova3D's Blender scripts name every mesh object).

The call site in `from_api()` is already:
```python
parts = _extract_part_names(unwrapped, joints)
```
`unwrapped` is the full result dict — it already has access to `parts` and `code_artifact`. No call site change needed.

- [ ] **Step 1: Write two failing tests**

Append to `tests/test_client.py`:

```python
def test_result_parsing_parts_from_code_artifact():
    data = {
        "sketch_to_3d_generator": [
            {
                "result": {
                    "model_url": "https://nova3d.xyz/assets/abc123.glb",
                    "model_artifact": {"url": "https://nova3d.xyz/assets/abc123.glb"},
                    "code_artifact": {
                        "content": (
                            "import bpy\n"
                            "bpy.ops.mesh.primitive_cube_add()\n"
                            "obj = bpy.context.active_object\n"
                            "obj.name = \"body\"\n"
                            "bpy.ops.mesh.primitive_cylinder_add()\n"
                            "wheel = bpy.context.active_object\n"
                            "wheel.name = \"wheel_fr\"\n"
                        )
                    },
                }
            }
        ]
    }
    result = GenerationResult.from_api(data, WORKFLOW_ID)
    assert result.parts == ["body", "wheel_fr"]


def test_result_parsing_parts_api_field_takes_precedence():
    data = {
        "sketch_to_3d_generator": [
            {
                "result": {
                    "model_url": "https://nova3d.xyz/assets/abc123.glb",
                    "model_artifact": {"url": "https://nova3d.xyz/assets/abc123.glb"},
                    "code_artifact": {
                        "content": 'obj.name = "should_not_appear"'
                    },
                    "parts": ["door", "frame"],
                }
            }
        ]
    }
    result = GenerationResult.from_api(data, WORKFLOW_ID)
    assert result.parts == ["door", "frame"]
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/hassan/Desktop/nova3d-mcp && .venv/bin/pytest tests/test_client.py::test_result_parsing_parts_from_code_artifact tests/test_client.py::test_result_parsing_parts_api_field_takes_precedence -v
```

Expected: both FAILED — `parts` returns `[]` for the first test, `[]` for the second.

- [ ] **Step 3: Add `import re` to `nova3d_mcp/models.py`**

In `nova3d_mcp/models.py`, replace:

```python
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
```

With:

```python
from __future__ import annotations

import re
from enum import Enum
from typing import Any, Dict, List, Optional
```

- [ ] **Step 4: Replace `_extract_part_names()` in `nova3d_mcp/models.py`**

Find and replace the entire function (currently lines 275–285):

OLD:
```python
def _extract_part_names(
    unwrapped: Dict[str, Any],
    joints: List[Dict[str, Any]],
) -> List[str]:
    """Extract named part/mesh identifiers from joints or code artifact."""
    names: List[str] = []
    for joint in joints:
        mesh = joint.get("mesh") or joint.get("name")
        if isinstance(mesh, str) and mesh.strip():
            names.append(mesh.strip())
    return list(dict.fromkeys(names))  # deduplicate, preserve order
```

NEW:
```python
def _extract_part_names(
    unwrapped: Dict[str, Any],
    joints: List[Dict[str, Any]],
) -> List[str]:
    """Extract named part/mesh identifiers from the result."""
    # 1. API-first: use explicit parts field if the backend returns one
    api_parts = unwrapped.get("parts")
    if isinstance(api_parts, list) and api_parts:
        return [str(p) for p in api_parts if p]

    # 2. Regex over Blender construction script — obj.name = "part_name"
    code_artifact = unwrapped.get("code_artifact")
    if isinstance(code_artifact, dict):
        content = code_artifact.get("content") or ""
        if content:
            names = re.findall(r'\.name\s*=\s*["\']([^"\']+)["\']', content)
            if names:
                return list(dict.fromkeys(names))  # deduplicate, preserve order

    # 3. Fallback: extract from joints (articulated assets)
    names = []
    for joint in joints:
        mesh = joint.get("mesh") or joint.get("name")
        if isinstance(mesh, str) and mesh.strip():
            names.append(mesh.strip())
    return list(dict.fromkeys(names))
```

- [ ] **Step 5: Run new tests — expect both PASSED**

```bash
cd /home/hassan/Desktop/nova3d-mcp && .venv/bin/pytest tests/test_client.py::test_result_parsing_parts_from_code_artifact tests/test_client.py::test_result_parsing_parts_api_field_takes_precedence -v
```

Expected: both PASSED.

- [ ] **Step 6: Run full suite — no regressions**

```bash
cd /home/hassan/Desktop/nova3d-mcp && .venv/bin/pytest -v
```

Expected: all 20 existing tests + 2 new = 22 tests pass.

- [ ] **Step 7: Commit**

```bash
cd /home/hassan/Desktop/nova3d-mcp && git add nova3d_mcp/models.py tests/test_client.py && git commit -m "fix: extract part names from code artifact — parts no longer returns empty for non-articulated assets"
```

---

## Task 2: Create `server.json` and `.env.example`

**Files:**
- Create: `server.json` (repo root)
- Create: `.env.example` (repo root)

No tests — these are static files. Verified by reading them after creation.

- [ ] **Step 1: Create `server.json` at repo root**

Create `/home/hassan/Desktop/nova3d-mcp/server.json` with this exact content:

```json
{
  "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
  "name": "io.github.raresense/nova3d-mcp",
  "title": "Nova3D",
  "description": "Structured, part-aware 3D generation for AI agents. Named-part GLB, preview URL, Blender script.",
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

- [ ] **Step 2: Create `.env.example` at repo root**

Create `/home/hassan/Desktop/nova3d-mcp/.env.example` with this exact content:

```
# Nova3D MCP Server — environment variables
# Copy to .env and fill in your values

# Required: API key from nova3d.xyz → Settings → API Keys
NOVA3D_TOKEN=n3d_your-api-key-here

# Optional: override the API base URL (advanced / self-hosted only)
# NOVA3D_API_URL=https://nova3d.xyz/api
```

- [ ] **Step 3: Commit**

```bash
cd /home/hassan/Desktop/nova3d-mcp && git add server.json .env.example && git commit -m "feat: add server.json MCP registry manifest and .env.example"
```

---

## Task 3: Update README install and config sections

**Files:**
- Modify: `README.md`

No tests. Verified by reading the updated sections.

- [ ] **Step 1: Replace the `### 1. Install` section**

In `README.md`, replace:

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

With:

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

- [ ] **Step 2: Replace the `### 3. Add to Claude Code` section**

In `README.md`, replace:

```markdown
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
```

With:

```markdown
### 3. Add to Claude Code

**Once on PyPI:**
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

**From source (after `pip install .`):**
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
```

- [ ] **Step 3: Commit**

```bash
cd /home/hassan/Desktop/nova3d-mcp && git add README.md && git commit -m "docs: clarify install — uvx requires PyPI, add from-source path and Claude Code config"
```

---

## Self-Review

**Spec coverage:**

| Spec requirement | Task |
|---|---|
| `server.json` with correct schema, name, version, repo, packages | Task 2 Step 1 |
| `.env.example` with NOVA3D_TOKEN and commented NOVA3D_API_URL | Task 2 Step 2 |
| `_extract_part_names`: API-first check for `parts` field | Task 1 Step 4 |
| `_extract_part_names`: regex fallback on code_artifact.content | Task 1 Step 4 |
| `_extract_part_names`: joints fallback preserved | Task 1 Step 4 |
| Test: parts extracted from code artifact | Task 1 Step 1 |
| Test: API parts field takes precedence | Task 1 Step 1 |
| README install: `uvx` labelled as "coming soon" | Task 3 Step 1 |
| README install: from-source path added | Task 3 Step 1 |
| README Claude Code config: both uvx and from-source variants | Task 3 Step 2 |

**No placeholders found.** All steps contain complete code.

**Type consistency:** `_extract_part_names` signature unchanged (`unwrapped: Dict[str, Any], joints: List[Dict[str, Any]]) -> List[str]`). Call site in `from_api()` unchanged. `re.findall` returns `List[str]`. Consistent throughout.
