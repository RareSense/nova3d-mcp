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
