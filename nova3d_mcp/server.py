"""
nova3d_mcp/server.py
────────────────────────────────────────────────────────────────
Nova3D MCP Server.

Exposes Nova3D's structured 3D generation pipeline as MCP tools
callable from Claude Code, Cursor, and any MCP-compatible agent.

Configuration (environment variables):
    NOVA3D_TOKEN      — JWT from nova3d.xyz (required)
    NOVA3D_API_URL    — Override API base URL (optional)

Usage:
    uvx nova3d-mcp
    # or
    python -m nova3d_mcp.server
────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from nova3d_mcp.client import Nova3DClient, Nova3DAuthError, Nova3DError
from nova3d_mcp.models import PROVIDER_DEFAULT_MODELS

load_dotenv()

# ── Startup error state ───────────────────────────────────────────────────────

_startup_error: Optional[str] = None

# ── Server init ───────────────────────────────────────────────────────────────

mcp = FastMCP(
    "nova3d",
    instructions=(
        "Nova3D generates structured, part-aware 3D assets from text prompts or "
        "reference images. Unlike diffusion-based tools, Nova3D outputs named, "
        "separately editable mesh components — not fused blobs. "
        "Each tool call returns a GLB download URL and a browser preview URL "
        "where you can inspect and interact with the generated parts. "
        "Requires NOVA3D_TOKEN env var (JWT from nova3d.xyz) and a BYOK API key "
        "for your chosen LLM provider (Google, Anthropic, or OpenAI)."
    ),
)


# ── Auth helper ───────────────────────────────────────────────────────────────

def _get_token() -> str:
    token = os.environ.get("NOVA3D_TOKEN", "").strip()
    if not token:
        raise Nova3DError(
            "NOVA3D_TOKEN environment variable is not set. "
            "Sign in at nova3d.xyz, copy your token from Settings, "
            "and set it as NOVA3D_TOKEN."
        )
    return token


def _get_api_url() -> str:
    return os.environ.get("NOVA3D_API_URL", "https://nova3d.xyz/api").rstrip("/")


async def _validate_startup() -> None:
    """Validate NOVA3D_TOKEN against GET /api/me. Stores error in _startup_error instead of exiting."""
    global _startup_error

    token = os.environ.get("NOVA3D_TOKEN", "").strip()
    if not token:
        _startup_error = (
            "NOVA3D_TOKEN is not set. "
            "Create an API key at https://nova3d.xyz/settings → API Keys, "
            "then set it as NOVA3D_TOKEN in your MCP config and restart."
        )
        print(
            f"Nova3D: {_startup_error}",
            file=sys.stderr,
        )
        return

    base_url = _get_api_url()
    try:
        async with Nova3DClient(token=token, base_url=base_url) as client:
            me = await client.get_me()
        print(f"✓ Nova3D authenticated: {me['email']}", file=sys.stderr)
    except Nova3DAuthError as e:
        _startup_error = str(e)
        print(_startup_error, file=sys.stderr)
    except Nova3DError as e:
        _startup_error = (
            f"Could not reach Nova3D to verify token: {e}\n"
            "Check your connection and try again."
        )
        print(_startup_error, file=sys.stderr)


# ── Tools ─────────────────────────────────────────────────────────────────────

@mcp.tool()
async def generate_3d(
    prompt: str,
    provider: str,
    api_key: str,
    llm: Optional[str] = None,
    image_base64: Optional[str] = None,
    image_mime: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generate a structured, part-aware 3D asset from a text prompt.

    Nova3D writes Blender Python construction code, executes it server-side,
    validates spatial structure, and exports a GLB with named, separately
    addressable parts — not a fused mesh blob.

    Args:
        prompt:       Description of the 3D asset. Be specific about parts.
                      Example: "a washing machine with drum, door, control panel,
                      and hose connectors"
        provider:     LLM provider to use. One of: "google", "anthropic", "openai".
                      Gemini is recommended for best spatial reasoning.
        api_key:      Your API key for the specified provider (BYOK).
        llm:          Model identifier. Defaults to the recommended model for
                      the provider if not specified.
                      google → "gemini-2.0-flash"
                      anthropic → "claude-sonnet-4-20250514"
                      openai → "gpt-4o"
        image_base64: Optional reference image as plain base64 (not a data URL).
        image_mime:   MIME type of the reference image e.g. "image/jpeg".

    Returns:
        glb_url:       Direct download URL for the structured GLB file.
        preview_url:   Browser URL for interactive Three.js viewer with named
                       parts, orbit controls, and part explosion.
                       Open this to visually verify the result.
        parts:         List of named mesh/joint identifiers in the asset.
        joint_count:   Number of articulated joints.
        code_artifact: Blender Python construction script. Pass this to
                       regenerate_part, add_part, or articulate_model.
        model_artifact: GLB artifact object. Pass to articulate_model.
        workflow_id:   Workflow identifier for status tracking.
        failed:        True if generation failed.
        error_message: Human-readable error if failed is True.
    """
    if _startup_error:
        return {"failed": True, "error_message": _startup_error}
    resolved_llm = llm or PROVIDER_DEFAULT_MODELS.get(provider, "gemini-2.0-flash")
    token = _get_token()
    base_url = _get_api_url()

    async with Nova3DClient(token=token, base_url=base_url) as client:
        result = await client.generate(
            prompt=prompt,
            provider=provider,
            llm=resolved_llm,
            api_key=api_key,
            image_base64=image_base64,
            image_mime=image_mime,
        )

    if result.failed:
        return {
            "failed": True,
            "error_message": result.error_message,
            "error_category": result.error_category,
            "retryable": result.retryable,
        }

    return {
        "glb_url": result.glb_url,
        "preview_url": result.preview_url,
        "parts": result.parts,
        "joint_count": result.joint_count,
        "joints": result.joints,
        "code_artifact": result.code_artifact,
        "model_artifact": result.model_artifact,
        "workflow_id": result.workflow_id,
        "api_key_source": result.api_key_source,
        "failed": False,
    }


@mcp.tool()
async def regenerate_part(
    code_artifact: Dict[str, Any],
    part_type: str,
    description: str,
    provider: str,
    api_key: str,
    llm: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Regenerate a specific named part within an existing 3D asset.

    Use this after generate_3d when you want to change one component without
    rebuilding the entire asset. The part name must match a name from the
    parts list returned by the original generate_3d call, or a name visible
    in the preview viewer.

    Args:
        code_artifact: The code_artifact object from a prior generate_3d or
                       edit workflow result. Required — this is how Nova3D
                       knows the current structure of the asset.
        part_type:     Name of the part to regenerate. Must match a part name
                       from the asset. Example: "door", "handle", "drum",
                       "control_panel". Check the preview URL to identify
                       exact part names.
        description:   Description of what the regenerated part should look
                       like. Be specific. Example: "glass panel door with
                       chrome frame and rubber seal around the edges".
        provider:      LLM provider. One of: "google", "anthropic", "openai".
        api_key:       Your API key for the specified provider (BYOK).
        llm:           Model identifier. Defaults to provider's recommended model.

    Returns:
        glb_url:       Updated GLB with the regenerated part.
        preview_url:   Browser preview URL for the updated asset.
        code_artifact: Updated construction script for further edits.
        workflow_id:   Workflow identifier.
        failed:        True if regeneration failed.
        error_message: Human-readable error if failed is True.
    """
    if _startup_error:
        return {"failed": True, "error_message": _startup_error}
    resolved_llm = llm or PROVIDER_DEFAULT_MODELS.get(provider, "gemini-2.0-flash")
    token = _get_token()
    base_url = _get_api_url()

    async with Nova3DClient(token=token, base_url=base_url) as client:
        result = await client.regenerate_part(
            code_artifact=code_artifact,
            part_type=part_type,
            description=description,
            provider=provider,
            llm=resolved_llm,
            api_key=api_key,
        )

    if result.failed:
        return {
            "failed": True,
            "error_message": result.error_message,
            "error_category": result.error_category,
            "retryable": result.retryable,
        }

    return {
        "glb_url": result.glb_url,
        "preview_url": result.preview_url,
        "parts": result.parts,
        "code_artifact": result.code_artifact,
        "workflow_id": result.workflow_id,
        "api_key_source": result.api_key_source,
        "failed": False,
    }


@mcp.tool()
async def add_part(
    code_artifact: Dict[str, Any],
    description: str,
    provider: str,
    api_key: str,
    llm: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Add a new named part to an existing 3D asset.

    Use this to extend an asset with additional components after the initial
    generation. The new part is integrated into the scene graph alongside the
    existing parts, preserving all naming and hierarchy.

    Args:
        code_artifact: The code_artifact object from a prior generate_3d or
                       edit workflow result.
        description:   Description of the new part to add. Be specific about
                       shape, position relative to existing parts, and any
                       material properties. Example: "add a chrome handle bar
                       to the front face of the door, centered horizontally".
        provider:      LLM provider. One of: "google", "anthropic", "openai".
        api_key:       Your API key for the specified provider (BYOK).
        llm:           Model identifier. Defaults to provider's recommended model.

    Returns:
        glb_url:       Updated GLB with the new part added.
        preview_url:   Browser preview URL showing the expanded asset.
        parts:         Updated list of part names including the new part.
        code_artifact: Updated construction script for further edits.
        workflow_id:   Workflow identifier.
        failed:        True if the add operation failed.
        error_message: Human-readable error if failed is True.
    """
    if _startup_error:
        return {"failed": True, "error_message": _startup_error}
    resolved_llm = llm or PROVIDER_DEFAULT_MODELS.get(provider, "gemini-2.0-flash")
    token = _get_token()
    base_url = _get_api_url()

    async with Nova3DClient(token=token, base_url=base_url) as client:
        result = await client.add_part(
            code_artifact=code_artifact,
            description=description,
            provider=provider,
            llm=resolved_llm,
            api_key=api_key,
        )

    if result.failed:
        return {
            "failed": True,
            "error_message": result.error_message,
            "error_category": result.error_category,
            "retryable": result.retryable,
        }

    return {
        "glb_url": result.glb_url,
        "preview_url": result.preview_url,
        "parts": result.parts,
        "code_artifact": result.code_artifact,
        "workflow_id": result.workflow_id,
        "api_key_source": result.api_key_source,
        "failed": False,
    }


@mcp.tool()
async def articulate_model(
    code_artifact: Dict[str, Any],
    model_url: str,
    articulation_request: str,
    provider: str,
    api_key: str,
    llm: Optional[str] = None,
    selected_meshes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Add joints, hinges, or rotational articulation to an existing 3D asset.

    Use this to make parts of a generated asset physically movable — rotating
    drums, swinging doors, articulated robot joints, etc. The articulation is
    real and exported as joint definitions in the GLB, not baked into the mesh.

    Args:
        code_artifact:        The code_artifact object from a prior generation.
        model_url:            The glb_url from the prior generation result.
                              Must be a direct HTTPS URL, not a blob: URL.
        articulation_request: Plain language description of the desired
                              articulation. Example: "make the drum rotate
                              around its central axis and the door swing open
                              on a hinge at the left edge".
        provider:             LLM provider. One of: "google", "anthropic", "openai".
        api_key:              Your API key for the specified provider (BYOK).
        llm:                  Model identifier. Defaults to provider's recommended model.
        selected_meshes:      Optional list of specific mesh names to articulate.
                              If omitted, the LLM infers which parts to articulate
                              from the articulation_request.

    Returns:
        glb_url:       Updated GLB with joint definitions embedded.
        preview_url:   Browser preview URL where articulation can be tested.
        joints:        List of joint definition objects.
        joint_count:   Number of joints added.
        code_artifact: Updated construction script.
        workflow_id:   Workflow identifier.
        failed:        True if articulation failed.
        error_message: Human-readable error if failed is True.
    """
    if _startup_error:
        return {"failed": True, "error_message": _startup_error}
    resolved_llm = llm or PROVIDER_DEFAULT_MODELS.get(provider, "gemini-2.0-flash")
    token = _get_token()
    base_url = _get_api_url()

    async with Nova3DClient(token=token, base_url=base_url) as client:
        result = await client.articulate_model(
            code_artifact=code_artifact,
            model_url=model_url,
            articulation_request=articulation_request,
            provider=provider,
            llm=resolved_llm,
            api_key=api_key,
            selected_meshes=selected_meshes,
        )

    if result.failed:
        return {
            "failed": True,
            "error_message": result.error_message,
            "error_category": result.error_category,
            "retryable": result.retryable,
        }

    return {
        "glb_url": result.glb_url,
        "preview_url": result.preview_url,
        "joints": result.joints,
        "joint_count": result.joint_count,
        "code_artifact": result.code_artifact,
        "workflow_id": result.workflow_id,
        "api_key_source": result.api_key_source,
        "failed": False,
    }


@mcp.tool()
async def get_generation_status(workflow_id: str) -> Dict[str, Any]:
    """
    Get the current status of a running generation workflow.

    Use this to check on a long-running generation without waiting for
    the full result. The generate_3d and edit tools block until completion,
    but this tool is useful if you have a workflow_id from a prior session.

    Args:
        workflow_id: The workflow_id returned by any generation tool.

    Returns:
        state:          Current state string.
        is_terminal:    True if the workflow has finished (success or failure).
        progress_label: Human-readable progress description.
        current_node:   Internal pipeline node currently executing.
    """
    if _startup_error:
        return {"failed": True, "error_message": _startup_error}
    token = _get_token()
    base_url = _get_api_url()

    async with Nova3DClient(token=token, base_url=base_url) as client:
        status = await client.get_status(workflow_id)

    return {
        "workflow_id": status.workflow_id,
        "state": status.state.value,
        "is_terminal": status.is_terminal,
        "progress_label": status.progress_label,
        "current_node": status.current_node,
    }


# ── Entrypoint ────────────────────────────────────────────────────────────────

def main() -> None:
    asyncio.run(_validate_startup())
    mcp.run()


if __name__ == "__main__":
    main()
