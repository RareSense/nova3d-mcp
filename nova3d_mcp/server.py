"""
nova3d_mcp/server.py
────────────────────────────────────────────────────────────────
Nova3D MCP Server.

Exposes Nova3D's structured 3D generation pipeline as MCP tools
callable from Claude Code, Cursor, and any MCP-compatible agent.

Configuration (environment variables):
    NOVA3D_TOKEN      — JWT from nova3d.xyz (required)
    NOVA3D_API_URL    — Override API base URL (optional)
    NOVA3D_APP_URL    — Override app URL for conversation links (optional)

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
from typing import Any, Awaitable, Callable, Dict, List, Optional

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import Context

from nova3d_mcp.client import Nova3DClient, Nova3DAuthError, Nova3DError
from nova3d_mcp.conversation import (
    build_edit_message,
    build_generation_messages,
)
from nova3d_mcp.models import GenerationResult
from nova3d_mcp.models import WorkflowStatus

load_dotenv()

# ── Startup error state ───────────────────────────────────────────────────────

_startup_error: Optional[str] = None

# ── Model options ─────────────────────────────────────────────────────────────

_MODEL_OPTIONS: Dict[str, Dict[str, str]] = {
    "gemini": {
        "provider": "gemini",
        "llm": "gemini",
        "option_id": "gemini_gemini",
    },
    "claude-sonnet": {
        "provider": "anthropic",
        "llm": "claude-sonnet",
        "option_id": "anthropic_claude_sonnet",
    },
    "claude-opus": {
        "provider": "anthropic",
        "llm": "claude-opus",
        "option_id": "anthropic_claude_opus",
    },
    "claude-opus-latest": {
        "provider": "anthropic",
        "llm": "claude-opus-latest",
        "option_id": "anthropic_claude_opus_latest",
    },
    "gpt-5.5": {
        "provider": "openai",
        "llm": "gpt55",
        "option_id": "openai_gpt55",
    },
}
_DEFAULT_MODEL = "gemini"


def _resolve_model(model: Optional[str]) -> Optional[Dict[str, str]]:
    return _MODEL_OPTIONS.get((model or _DEFAULT_MODEL).strip())

# ── Server init ───────────────────────────────────────────────────────────────

mcp = FastMCP(
    "nova3d",
    instructions=(
        "Nova3D generates structured, part-aware 3D assets from text prompts or "
        "reference images. Unlike diffusion-based tools, Nova3D outputs named, "
        "separately editable mesh components — not fused blobs.\n\n"
        "WORKFLOW:\n"
        "1. Call generate_3d → returns glb_url (download), parts list, "
        "code_artifact, and "
        "conversation_url. Always surface conversation_url to the user — it opens "
        "a browser view of the asset and its full edit history in the Nova3D app.\n"
        "2. Call regenerate_part, add_part, or articulate_model with the "
        "code_artifact from any prior result. These tools return an updated glb_url "
        "and the same conversation_url, linking all edits into one session.\n"
        "   - conversation_url may be absent from edit-tool responses if session "
        "creation failed silently at generate time; generation still succeeded.\n"
        "   - Always pass the most recent code_artifact forward — it carries session "
        "state that links edits together.\n\n"
        "SETUP: This server requires one credential:\n"
        "NOVA3D_TOKEN — a Nova3D API key. If the user has not set this, "
        "proactively tell them: 'To use Nova3D, you need an API key. "
        "Get one at https://app.nova3d.xyz/api-key, then run: "
        "claude mcp add nova3d -e NOVA3D_TOKEN=n3d_your-key -- uvx nova3d-mcp'\n"
        "\n"
        "If any tool returns {\"failed\": true}, surface the error_message to the user verbatim."
    ),
)


# ── Auth helper ───────────────────────────────────────────────────────────────

def _get_token() -> str:
    token = os.environ.get("NOVA3D_TOKEN", "").strip()
    if not token:
        raise Nova3DError(
            "NOVA3D_TOKEN is not set. "
            "Get an API key at https://app.nova3d.xyz/api-key "
            "and add it with: claude mcp add nova3d -e NOVA3D_TOKEN=n3d_your-key -- uvx nova3d-mcp"
        )
    return token


def _get_api_url() -> str:
    return os.environ.get("NOVA3D_API_URL", "https://nova3d.xyz/api").rstrip("/")


def _get_app_url() -> str:
    return os.environ.get("NOVA3D_APP_URL", "https://app.nova3d.xyz").rstrip("/")


async def _validate_startup() -> None:
    """Validate NOVA3D_TOKEN against GET /api/me. Stores error in _startup_error instead of exiting."""
    global _startup_error

    token = os.environ.get("NOVA3D_TOKEN", "").strip()
    if not token:
        _startup_error = (
            "NOVA3D_TOKEN is not set. "
            "Get an API key at https://app.nova3d.xyz/api-key, "
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


# ── Progress helper ───────────────────────────────────────────────────────────

def _make_progress_callback(
    ctx: Optional[Context],
) -> Callable[[WorkflowStatus], Awaitable[None]]:
    """Return an async on_progress callback that reports each newly completed node."""
    seen: set = set()
    counter: List[int] = [0]

    async def on_progress(status: WorkflowStatus) -> None:
        node = status.last_exit_node or status.current_node
        if not node or node in seen:
            return
        seen.add(node)
        counter[0] += 1
        if ctx:
            await ctx.report_progress(
                progress=counter[0],
                total=None,
                message=f"Completed: {node}",
            )

    return on_progress


# ── Conversation linking helpers ──────────────────────────────────────────────

def _extract_conversation_id(code_artifact: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(code_artifact, dict):
        return None
    return code_artifact.get("_nova3d_conversation_id") or None


def _embed_code_artifact_metadata(
    code_artifact: Optional[Dict[str, Any]],
    conversation_id: Optional[str],
    *,
    source_code_artifact: Optional[Dict[str, Any]] = None,
    prompt: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    if code_artifact is None:
        return None
    result = dict(code_artifact)
    if conversation_id:
        result["_nova3d_conversation_id"] = conversation_id
    source_prompt = (
        source_code_artifact.get("_nova3d_prompt")
        if isinstance(source_code_artifact, dict)
        else None
    )
    final_prompt = prompt or source_prompt
    if final_prompt:
        result["_nova3d_prompt"] = final_prompt
    return result


def _conversation_url(app_url: str, conversation_id: Optional[str]) -> Optional[str]:
    if not conversation_id:
        return None
    return f"{app_url}/chat/{conversation_id}"


async def _persist_generation_history(
    client: Nova3DClient,
    *,
    conversation_id: Optional[str],
    title: str,
    prompt: str,
    result: GenerationResult,
    code_artifact: Optional[Dict[str, Any]],
    model_option_id: str,
) -> bool:
    if not conversation_id:
        return False
    messages = build_generation_messages(
        prompt=prompt,
        result=result,
        code_artifact=code_artifact,
        model_option_id=model_option_id,
    )
    try:
        await client.update_conversation_snapshot(
            conversation_id,
            title=title,
            messages=messages,
        )
        await _append_and_link_messages(client, conversation_id, messages)
        return True
    except Nova3DError as e:
        print(f"Nova3D: conversation history persistence failed: {e}", file=sys.stderr)
        return False


async def _persist_edit_history(
    client: Nova3DClient,
    *,
    conversation_id: Optional[str],
    operation: str,
    description: str,
    result: GenerationResult,
    code_artifact: Optional[Dict[str, Any]],
    model_option_id: str,
    instruction_prompt: Optional[str],
) -> bool:
    if not conversation_id:
        return False
    message = build_edit_message(
        operation=operation,
        description=description,
        result=result,
        code_artifact=code_artifact,
        model_option_id=model_option_id,
        instruction_prompt=instruction_prompt,
    )
    try:
        await _append_and_link_messages(client, conversation_id, [message])
        return True
    except Nova3DError as e:
        print(f"Nova3D: edit history persistence failed: {e}", file=sys.stderr)
        return False


async def _append_and_link_messages(
    client: Nova3DClient,
    conversation_id: str,
    messages: List[Dict[str, Any]],
) -> None:
    for message in messages:
        remote_message_id = await client.append_conversation_message(
            conversation_id,
            message,
        )
        workflow_id = message.get("workflow_id")
        if workflow_id:
            await client.link_workflow_to_message(
                conversation_id,
                workflow_id=str(workflow_id),
                remote_message_id=remote_message_id,
                operation=str(message.get("operation") or "generation"),
            )


# ── Tools ─────────────────────────────────────────────────────────────────────

@mcp.tool()
async def nova3d_setup() -> Dict[str, Any]:
    """
    Get setup instructions for Nova3D.

    Call this if the user asks how to get started, needs an API key,
    or hasn't configured NOVA3D_TOKEN yet.

    Returns:
        instructions: Step-by-step setup guide with URL and install command.
    """
    instructions = (
        "To use Nova3D you need one thing:\n"
        "A Nova3D API key — get one at https://app.nova3d.xyz/api-key\n\n"
        "Once you have it, run:\n"
        "claude mcp add nova3d -e NOVA3D_TOKEN=n3d_your-key -- uvx nova3d-mcp"
    )
    return {"instructions": instructions}


@mcp.tool()
async def generate_3d(
    prompt: str,
    model: Optional[str] = None,
    image_base64: Optional[str] = None,
    image_mime: Optional[str] = None,
    ctx: Optional[Context] = None,
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
        model:        LLM model to use. One of: "gemini" (default), "claude-sonnet",
                      "claude-opus", "claude-opus-latest", "gpt-5.5".
        image_base64: Optional reference image as plain base64 (not a data URL).
        image_mime:   MIME type of the reference image e.g. "image/jpeg".

    Returns:
        glb_url:       Direct download URL for the structured GLB file.
        parts:         List of named mesh/joint identifiers in the asset.
        joint_count:   Number of articulated joints.
        code_artifact: Blender Python construction script. Pass this to
                       regenerate_part, add_part, or articulate_model.
        model_artifact: GLB artifact object. Pass to articulate_model.
        workflow_id:       Workflow identifier for status tracking.
        conversation_url:  Browser URL for the editing session in the Nova3D app.
                           All regenerate/edit calls on this asset link here too.
                           Open this to see the full generation history for this asset.
        failed:            True if generation failed.
        error_message:     Human-readable error if failed is True.
    """
    if _startup_error:
        return {"failed": True, "error_message": _startup_error}
    model_opts = _resolve_model(model)
    if model_opts is None:
        valid = ", ".join(_MODEL_OPTIONS)
        return {"failed": True, "error_message": f"Invalid model '{model or _DEFAULT_MODEL}'. Valid options: {valid}"}
    token = _get_token()
    base_url = _get_api_url()
    app_url = _get_app_url()

    async with Nova3DClient(token=token, base_url=base_url) as client:
        conversation_id: Optional[str] = None
        try:
            conversation_id = await client.create_conversation(title=prompt[:100])
        except Exception as e:
            print(f"Nova3D: conversation creation failed (generation will proceed): {e}", file=sys.stderr)

        result = await client.generate(
            prompt=prompt,
            provider=model_opts["provider"],
            llm=model_opts["llm"],
            image_base64=image_base64,
            image_mime=image_mime,
            conversation_id=conversation_id,
            on_progress=_make_progress_callback(ctx),
        )

        if result.failed:
            return {
                "failed": True,
                "error_message": result.error_message,
                "error_category": result.error_category,
                "retryable": result.retryable,
            }

        code_artifact = _embed_code_artifact_metadata(
            result.code_artifact or {},
            conversation_id,
            prompt=prompt,
        )
        history_persisted = await _persist_generation_history(
            client,
            conversation_id=conversation_id,
            title=prompt[:100],
            prompt=prompt,
            result=result,
            code_artifact=code_artifact,
            model_option_id=model_opts["option_id"],
        )

    response: Dict[str, Any] = {
        "glb_url": result.glb_url,
        "parts": result.parts,
        "joint_count": result.joint_count,
        "joints": result.joints,
        "code_artifact": code_artifact,
        "model_artifact": result.model_artifact,
        "workflow_id": result.workflow_id,
        "api_key_source": result.api_key_source,
        "history_persisted": history_persisted,
        "failed": False,
    }
    conv_url = _conversation_url(app_url, conversation_id)
    if conv_url:
        response["conversation_url"] = conv_url
    return response


@mcp.tool()
async def regenerate_part(
    code_artifact: Dict[str, Any],
    part_type: str,
    description: str,
    model: Optional[str] = None,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """
    Regenerate a specific named part within an existing 3D asset.

    Use this after generate_3d when you want to change one component without
    rebuilding the entire asset. The part name must match a name from the
    parts list returned by the original generate_3d call, or a part name visible
    in the conversation viewer.

    Args:
        code_artifact: The code_artifact object from a prior generate_3d or
                       edit workflow result. Required — this is how Nova3D
                       knows the current structure of the asset.
        part_type:     Name of the part to regenerate. Must match a part name
                       from the asset. Example: "door", "handle", "drum",
                       "control_panel". Check the conversation URL to identify
                       exact part names.
        description:   Description of what the regenerated part should look
                       like. Be specific. Example: "glass panel door with
                       chrome frame and rubber seal around the edges".
        model:         LLM model. One of: "gemini" (default), "claude-sonnet",
                       "claude-opus", "claude-opus-latest", "gpt-5.5".

    Returns:
        glb_url:           Updated GLB with the regenerated part.
        code_artifact:     Updated construction script for further edits.
        workflow_id:       Workflow identifier.
        conversation_url:  Browser URL for the editing session. Present only if
                           the original generate_3d call successfully created a
                           conversation. Same URL as returned by generate_3d.
        failed:            True if regeneration failed.
        error_message:     Human-readable error if failed is True.
    """
    if _startup_error:
        return {"failed": True, "error_message": _startup_error}
    model_opts = _resolve_model(model)
    if model_opts is None:
        valid = ", ".join(_MODEL_OPTIONS)
        return {"failed": True, "error_message": f"Invalid model '{model or _DEFAULT_MODEL}'. Valid options: {valid}"}
    token = _get_token()
    base_url = _get_api_url()
    app_url = _get_app_url()
    conversation_id = _extract_conversation_id(code_artifact)

    async with Nova3DClient(token=token, base_url=base_url) as client:
        result = await client.regenerate_part(
            code_artifact=code_artifact,
            part_type=part_type,
            description=description,
            provider=model_opts["provider"],
            llm=model_opts["llm"],
            conversation_id=conversation_id,
            on_progress=_make_progress_callback(ctx),
        )

        if result.failed:
            return {
                "failed": True,
                "error_message": result.error_message,
                "error_category": result.error_category,
                "retryable": result.retryable,
            }

        updated_code_artifact = _embed_code_artifact_metadata(
            result.code_artifact,
            conversation_id,
            source_code_artifact=code_artifact,
        )
        history_persisted = await _persist_edit_history(
            client,
            conversation_id=conversation_id,
            operation="regenerate_3d_part",
            description=description,
            result=result,
            code_artifact=updated_code_artifact,
            model_option_id=model_opts["option_id"],
            instruction_prompt=(
                code_artifact.get("_nova3d_prompt")
                if isinstance(code_artifact, dict)
                else None
            ),
        )

    response: Dict[str, Any] = {
        "glb_url": result.glb_url,
        "parts": result.parts,
        "code_artifact": updated_code_artifact,
        "workflow_id": result.workflow_id,
        "api_key_source": result.api_key_source,
        "history_persisted": history_persisted,
        "failed": False,
    }
    conv_url = _conversation_url(app_url, conversation_id)
    if conv_url:
        response["conversation_url"] = conv_url
    return response


@mcp.tool()
async def add_part(
    code_artifact: Dict[str, Any],
    description: str,
    model: Optional[str] = None,
    ctx: Optional[Context] = None,
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
        model:         LLM model. One of: "gemini" (default), "claude-sonnet",
                       "claude-opus", "claude-opus-latest", "gpt-5.5".

    Returns:
        glb_url:           Updated GLB with the new part added.
        parts:             Updated list of part names including the new part.
        code_artifact:     Updated construction script for further edits.
        workflow_id:       Workflow identifier.
        conversation_url:  Browser URL for the editing session. Present only if
                           the original generate_3d call successfully created a
                           conversation. Same URL as returned by generate_3d.
        failed:            True if the add operation failed.
        error_message:     Human-readable error if failed is True.
    """
    if _startup_error:
        return {"failed": True, "error_message": _startup_error}
    model_opts = _resolve_model(model)
    if model_opts is None:
        valid = ", ".join(_MODEL_OPTIONS)
        return {"failed": True, "error_message": f"Invalid model '{model or _DEFAULT_MODEL}'. Valid options: {valid}"}
    token = _get_token()
    base_url = _get_api_url()
    app_url = _get_app_url()
    conversation_id = _extract_conversation_id(code_artifact)

    async with Nova3DClient(token=token, base_url=base_url) as client:
        result = await client.add_part(
            code_artifact=code_artifact,
            description=description,
            provider=model_opts["provider"],
            llm=model_opts["llm"],
            conversation_id=conversation_id,
            on_progress=_make_progress_callback(ctx),
        )

        if result.failed:
            return {
                "failed": True,
                "error_message": result.error_message,
                "error_category": result.error_category,
                "retryable": result.retryable,
            }

        updated_code_artifact = _embed_code_artifact_metadata(
            result.code_artifact,
            conversation_id,
            source_code_artifact=code_artifact,
        )
        history_persisted = await _persist_edit_history(
            client,
            conversation_id=conversation_id,
            operation="add_3d_part",
            description=description,
            result=result,
            code_artifact=updated_code_artifact,
            model_option_id=model_opts["option_id"],
            instruction_prompt=(
                code_artifact.get("_nova3d_prompt")
                if isinstance(code_artifact, dict)
                else None
            ),
        )

    response: Dict[str, Any] = {
        "glb_url": result.glb_url,
        "parts": result.parts,
        "code_artifact": updated_code_artifact,
        "workflow_id": result.workflow_id,
        "api_key_source": result.api_key_source,
        "history_persisted": history_persisted,
        "failed": False,
    }
    conv_url = _conversation_url(app_url, conversation_id)
    if conv_url:
        response["conversation_url"] = conv_url
    return response


@mcp.tool()
async def articulate_model(
    code_artifact: Dict[str, Any],
    articulation_request: str,
    model_url: Optional[str] = None,
    model_artifact: Optional[Dict[str, Any]] = None,
    model: Optional[str] = None,
    selected_meshes: Optional[List[str]] = None,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """
    Add joints, hinges, or rotational articulation to an existing 3D asset.

    Use this to make parts of a generated asset physically movable — rotating
    drums, swinging doors, articulated robot joints, etc. The articulation is
    real and exported as joint definitions in the GLB, not baked into the mesh.

    Args:
        code_artifact:        The code_artifact object from a prior generation.
        articulation_request: Plain language description of the desired
                              articulation. Example: "make the drum rotate
                              around its central axis and the door swing open
                              on a hinge at the left edge".
        model_url:            The glb_url from the prior generation result.
                              Provide this or model_artifact (or both).
                              Must be a direct HTTPS URL, not a blob: URL.
        model_artifact:       The model_artifact object from the prior generation
                              result. Provide this or model_url (or both).
        model:                LLM model. One of: "gemini" (default), "claude-sonnet",
                              "claude-opus", "claude-opus-latest", "gpt-5.5".
        selected_meshes:      Optional list of specific mesh names to articulate.
                              If omitted, the LLM infers which parts to articulate
                              from the articulation_request.

    Returns:
        glb_url:           Updated GLB with joint definitions embedded.
        joints:            List of joint definition objects.
        joint_count:       Number of joints added.
        code_artifact:     Updated construction script.
        workflow_id:       Workflow identifier.
        conversation_url:  Browser URL for the editing session. Present only if
                           the original generate_3d call successfully created a
                           conversation. Same URL as returned by generate_3d.
        failed:            True if articulation failed.
        error_message:     Human-readable error if failed is True.
    """
    if _startup_error:
        return {"failed": True, "error_message": _startup_error}
    if model_url is None and model_artifact is None:
        return {
            "failed": True,
            "error_message": "Provide model_url or model_artifact from the prior generate_3d result.",
        }
    model_opts = _resolve_model(model)
    if model_opts is None:
        valid = ", ".join(_MODEL_OPTIONS)
        return {"failed": True, "error_message": f"Invalid model '{model or _DEFAULT_MODEL}'. Valid options: {valid}"}
    token = _get_token()
    base_url = _get_api_url()
    app_url = _get_app_url()
    conversation_id = _extract_conversation_id(code_artifact)
    instruction_prompt = code_artifact.get("_nova3d_prompt") if isinstance(code_artifact, dict) else None

    async with Nova3DClient(token=token, base_url=base_url) as client:
        result = await client.articulate_model(
            code_artifact=code_artifact,
            articulation_request=articulation_request,
            provider=model_opts["provider"],
            llm=model_opts["llm"],
            model_url=model_url,
            model_artifact=model_artifact,
            instruction_prompt=instruction_prompt,
            selected_meshes=selected_meshes,
            conversation_id=conversation_id,
            on_progress=_make_progress_callback(ctx),
        )

        if result.failed:
            return {
                "failed": True,
                "error_message": result.error_message,
                "error_category": result.error_category,
                "retryable": result.retryable,
            }

        updated_code_artifact = _embed_code_artifact_metadata(
            result.code_artifact,
            conversation_id,
            source_code_artifact=code_artifact,
        )
        history_persisted = await _persist_edit_history(
            client,
            conversation_id=conversation_id,
            operation="articulate_3d_model",
            description=articulation_request,
            result=result,
            code_artifact=updated_code_artifact,
            model_option_id=model_opts["option_id"],
            instruction_prompt=instruction_prompt,
        )

    response: Dict[str, Any] = {
        "glb_url": result.glb_url,
        "joints": result.joints,
        "joint_count": result.joint_count,
        "code_artifact": updated_code_artifact,
        "workflow_id": result.workflow_id,
        "api_key_source": result.api_key_source,
        "history_persisted": history_persisted,
        "failed": False,
    }
    conv_url = _conversation_url(app_url, conversation_id)
    if conv_url:
        response["conversation_url"] = conv_url
    return response


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
