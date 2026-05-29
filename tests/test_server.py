"""
tests/test_server.py
────────────────────────────────────────────────────────────────
Tests for server-level startup error propagation.
────────────────────────────────────────────────────────────────
"""
import pytest
import nova3d_mcp.server as server_module


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
        from nova3d_mcp.client import Nova3DAuthError
        with pytest.raises(Nova3DAuthError):
            await server_module.generate_3d(prompt="a chair", provider="google", api_key="fake")
