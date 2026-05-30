"""
tests/test_server.py
────────────────────────────────────────────────────────────────
Tests for server-level startup error propagation, setup tool,
and progress callback behaviour.
────────────────────────────────────────────────────────────────
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import nova3d_mcp.server as server_module
from nova3d_mcp.models import WorkflowStatus, WorkflowState


@pytest.fixture(autouse=True)
def reset_startup_error():
    """Reset _startup_error before and after every test."""
    server_module._startup_error = None
    yield
    server_module._startup_error = None


@pytest.mark.asyncio
async def test_generate_3d_returns_error_when_startup_failed():
    server_module._startup_error = (
        "Your NOVA3D_TOKEN is invalid. "
        "Check or create a key at nova3d.xyz → Settings → API Keys."
    )
    result = await server_module.generate_3d(
        prompt="a chair",
        provider="google",
        api_key="fake",
    )
    assert result["failed"] is True
    assert "nova3d.xyz" in result["error_message"]


@pytest.mark.asyncio
async def test_regenerate_part_returns_error_when_startup_failed():
    server_module._startup_error = "Your NOVA3D_TOKEN is invalid. Check or create a key at nova3d.xyz → Settings → API Keys."
    result = await server_module.regenerate_part(
        code_artifact={},
        part_type="door",
        description="glass door",
        provider="google",
        api_key="fake",
    )
    assert result["failed"] is True
    assert "nova3d.xyz" in result["error_message"]


@pytest.mark.asyncio
async def test_add_part_returns_error_when_startup_failed():
    server_module._startup_error = "Your NOVA3D_TOKEN is invalid. Check or create a key at nova3d.xyz → Settings → API Keys."
    result = await server_module.add_part(
        code_artifact={},
        description="a handle",
        provider="google",
        api_key="fake",
    )
    assert result["failed"] is True
    assert "nova3d.xyz" in result["error_message"]


@pytest.mark.asyncio
async def test_articulate_model_returns_error_when_startup_failed():
    server_module._startup_error = "Your NOVA3D_TOKEN is invalid. Check or create a key at nova3d.xyz → Settings → API Keys."
    result = await server_module.articulate_model(
        code_artifact={},
        model_url="https://nova3d.xyz/assets/abc.glb",
        articulation_request="make door swing",
        provider="google",
        api_key="fake",
    )
    assert result["failed"] is True
    assert "nova3d.xyz" in result["error_message"]


@pytest.mark.asyncio
async def test_get_generation_status_returns_error_when_startup_failed():
    server_module._startup_error = "Your NOVA3D_TOKEN is invalid. Check or create a key at nova3d.xyz → Settings → API Keys."
    result = await server_module.get_generation_status(workflow_id="state-123")
    assert result["failed"] is True
    assert "nova3d.xyz" in result["error_message"]


@pytest.mark.asyncio
async def test_generate_3d_proceeds_when_no_startup_error(monkeypatch):
    """Regression guard: no startup error means the tool runs normally, not short-circuited by the flag."""
    import respx
    import httpx

    server_module._startup_error = None
    monkeypatch.setenv("NOVA3D_TOKEN", "fake-token")

    with respx.mock(base_url="https://nova3d.xyz/api", assert_all_called=False) as mock:
        mock.get("/workflow/readiness/sketch_to_3d").mock(
            return_value=httpx.Response(401, json={"detail": {"code": "invalid_api_key", "message": "bad key"}})
        )
        mock.post("/conversations").mock(
            return_value=httpx.Response(201, json={"id": "conv-test"})
        )
        from nova3d_mcp.client import Nova3DAuthError
        with pytest.raises(Nova3DAuthError):
            await server_module.generate_3d(prompt="a chair", provider="google", api_key="fake")


@pytest.mark.asyncio
async def test_generate_3d_creates_conversation_and_returns_url(monkeypatch):
    """generate_3d creates a conversation and embeds its ID in code_artifact."""
    monkeypatch.setenv("NOVA3D_TOKEN", "n3d_testkey")
    monkeypatch.setenv("NOVA3D_API_URL", "https://nova3d.xyz/api")

    fake_result = MagicMock()
    fake_result.failed = False
    fake_result.glb_url = "https://nova3d.xyz/assets/abc.glb"
    fake_result.preview_url = "https://nova3d.xyz/preview/wf-123"
    fake_result.parts = ["body", "door"]
    fake_result.joint_count = 0
    fake_result.joints = []
    fake_result.code_artifact = {"content": "import bpy"}
    fake_result.model_artifact = None
    fake_result.workflow_id = "wf-123"
    fake_result.api_key_source = "request"

    mock_client = AsyncMock()
    mock_client.create_conversation = AsyncMock(return_value="conv-xyz")
    mock_client.generate = AsyncMock(return_value=fake_result)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("nova3d_mcp.server.Nova3DClient", return_value=mock_client):
        result = await server_module.generate_3d(
            prompt="a washing machine",
            provider="google",
            api_key="AIza-test",
        )

    assert result["failed"] is False
    assert result["conversation_url"] == "https://nova3d.xyz/chat/conv-xyz"
    assert result["code_artifact"]["_nova3d_conversation_id"] == "conv-xyz"
    mock_client.create_conversation.assert_called_once_with(title="a washing machine")
    mock_client.generate.assert_called_once()
    call_kwargs = mock_client.generate.call_args.kwargs
    assert call_kwargs["conversation_id"] == "conv-xyz"


@pytest.mark.asyncio
async def test_generate_3d_conversation_failure_does_not_block_generation(monkeypatch):
    """If create_conversation raises, generation still proceeds and conversation_url is absent."""
    monkeypatch.setenv("NOVA3D_TOKEN", "n3d_testkey")
    monkeypatch.setenv("NOVA3D_API_URL", "https://nova3d.xyz/api")

    fake_result = MagicMock()
    fake_result.failed = False
    fake_result.glb_url = "https://nova3d.xyz/assets/abc.glb"
    fake_result.preview_url = "https://nova3d.xyz/preview/wf-123"
    fake_result.parts = ["body"]
    fake_result.joint_count = 0
    fake_result.joints = []
    fake_result.code_artifact = {"content": "import bpy"}
    fake_result.model_artifact = None
    fake_result.workflow_id = "wf-123"
    fake_result.api_key_source = "request"

    from nova3d_mcp.client import Nova3DError
    mock_client = AsyncMock()
    mock_client.create_conversation = AsyncMock(side_effect=Nova3DError("network error"))
    mock_client.generate = AsyncMock(return_value=fake_result)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("nova3d_mcp.server.Nova3DClient", return_value=mock_client):
        result = await server_module.generate_3d(
            prompt="a chair",
            provider="google",
            api_key="AIza-test",
        )

    assert result["failed"] is False
    assert "conversation_url" not in result
    assert "_nova3d_conversation_id" not in result.get("code_artifact", {})
    mock_client.generate.assert_called_once()
    assert mock_client.generate.call_args.kwargs["conversation_id"] is None


# ── nova3d_setup tests ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_nova3d_setup_returns_url_and_command():
    result = await server_module.nova3d_setup()
    assert "nova3d.xyz/settings" in result["instructions"]
    assert "claude mcp add nova3d" in result["instructions"]
    assert "n3d_your-key" in result["instructions"]


@pytest.mark.asyncio
async def test_nova3d_setup_available_when_startup_error_set():
    """Setup instructions must be reachable even with no token configured."""
    server_module._startup_error = "NOVA3D_TOKEN is not set."
    result = await server_module.nova3d_setup()
    assert "nova3d.xyz/settings" in result["instructions"]


# ── Progress callback tests ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_progress_callback_reports_new_node():
    ctx = MagicMock()
    ctx.report_progress = AsyncMock()

    callback = server_module._make_progress_callback(ctx)
    status = WorkflowStatus(
        workflow_id="state-123",
        state=WorkflowState.RUNNING,
        last_exit_node="blender_code_generator",
    )
    await callback(status)

    ctx.report_progress.assert_called_once_with(
        progress=1, total=None, message="Completed: blender_code_generator"
    )


@pytest.mark.asyncio
async def test_progress_callback_deduplicates_same_node():
    ctx = MagicMock()
    ctx.report_progress = AsyncMock()

    callback = server_module._make_progress_callback(ctx)
    status = WorkflowStatus(
        workflow_id="state-123",
        state=WorkflowState.RUNNING,
        last_exit_node="blender_code_generator",
    )
    await callback(status)
    await callback(status)  # same node — should not fire again

    ctx.report_progress.assert_called_once()


@pytest.mark.asyncio
async def test_progress_callback_reports_each_new_node():
    ctx = MagicMock()
    ctx.report_progress = AsyncMock()

    callback = server_module._make_progress_callback(ctx)
    for node in ["blender_code_generator", "mesh_validator", "glb_exporter"]:
        await callback(WorkflowStatus(
            workflow_id="state-123",
            state=WorkflowState.RUNNING,
            last_exit_node=node,
        ))

    assert ctx.report_progress.call_count == 3
    messages = [call.kwargs["message"] for call in ctx.report_progress.call_args_list]
    assert messages == [
        "Completed: blender_code_generator",
        "Completed: mesh_validator",
        "Completed: glb_exporter",
    ]


@pytest.mark.asyncio
async def test_progress_callback_no_ctx_does_not_raise():
    """Regression guard: ctx=None (direct test calls) must not raise."""
    callback = server_module._make_progress_callback(None)
    status = WorkflowStatus(
        workflow_id="state-123",
        state=WorkflowState.RUNNING,
        last_exit_node="blender_code_generator",
    )
    await callback(status)  # should not raise


@pytest.mark.asyncio
async def test_progress_callback_skips_status_with_no_node():
    ctx = MagicMock()
    ctx.report_progress = AsyncMock()

    callback = server_module._make_progress_callback(ctx)
    status = WorkflowStatus(
        workflow_id="state-123",
        state=WorkflowState.RUNNING,
    )
    await callback(status)  # no node — nothing to report

    ctx.report_progress.assert_not_called()
