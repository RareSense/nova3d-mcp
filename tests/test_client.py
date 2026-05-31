"""
tests/test_client.py
────────────────────────────────────────────────────────────────
Unit tests for Nova3DClient.
Uses respx to mock HTTP without hitting the real API.
────────────────────────────────────────────────────────────────
"""
import pytest
import respx
import httpx

from nova3d_mcp.client import Nova3DClient, Nova3DError, Nova3DCreditsError, Nova3DAuthError
from nova3d_mcp.models import GenerationResult, WorkflowState


FAKE_TOKEN = "test-jwt-token"
BASE_URL = "https://nova3d.xyz/api"
WORKFLOW_ID = "state-123456789"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_api():
    with respx.mock(base_url=BASE_URL, assert_all_called=False) as mock:
        yield mock


def _readiness_ok():
    return {"ready": True, "reason": None, "projected_cost": 10, "authorized_budget": 12}


def _start_ok():
    return {
        "workflow_id": WORKFLOW_ID,
        "status_url": f"/status/{WORKFLOW_ID}",
        "result_url": f"/result/{WORKFLOW_ID}",
        "projected_cost": 10,
        "authorized_budget": 12,
    }


def _status_running():
    return {
        "runtime": {"state": "running", "last_exit_node_id": None},
        "node_visit_seq": {"sketch_to_3d_generator": 1},
    }


def _status_completed():
    return {
        "runtime": {"state": "completed", "last_exit_node_id": "success_final"},
        "node_visit_seq": {"sketch_to_3d_generator": 1},
    }


def _result_ok():
    return {
        "sketch_to_3d_generator": [
            {
                "result": {
                    "model_url": "https://nova3d.xyz/assets/abc123.glb",
                    "model_artifact": {"url": "https://nova3d.xyz/assets/abc123.glb"},
                    "code_artifact": {"content": "import bpy\n# generated code"},
                    "joints": [{"name": "door_hinge", "type": "revolute", "mesh": "door"}],
                    "joint_count": 1,
                    "operation": "sketch_to_3d",
                }
            }
        ]
    }


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_success(mock_api):
    mock_api.get("/workflow/readiness/sketch_to_3d").mock(
        return_value=httpx.Response(200, json=_readiness_ok())
    )
    mock_api.post("/run/state/sketch_to_3d").mock(
        return_value=httpx.Response(202, json=_start_ok())
    )
    # First status poll returns running, second returns completed
    mock_api.get(f"/status/{WORKFLOW_ID}").mock(
        side_effect=[
            httpx.Response(200, json=_status_running()),
            httpx.Response(200, json=_status_completed()),
        ]
    )
    mock_api.get(f"/result/{WORKFLOW_ID}").mock(
        return_value=httpx.Response(200, json=_result_ok())
    )

    async with Nova3DClient(token=FAKE_TOKEN, base_url=BASE_URL) as client:
        # Patch sleep to avoid actual waiting in tests
        import nova3d_mcp.client as client_module
        original_sleep = client_module.asyncio.sleep
        client_module.asyncio.sleep = lambda _: original_sleep(0)

        result = await client.generate(
            prompt="a toaster with removable tray",
            provider="google",
            llm="gemini-2.0-flash",
            api_key="AIza-test",
        )

        client_module.asyncio.sleep = original_sleep

    assert result.failed is False
    assert result.glb_url == "https://nova3d.xyz/assets/abc123.glb"
    assert result.joint_count == 1
    assert result.joints[0]["name"] == "door_hinge"
    assert result.workflow_id == WORKFLOW_ID


@pytest.mark.asyncio
async def test_generate_not_ready(mock_api):
    mock_api.get("/workflow/readiness/sketch_to_3d").mock(
        return_value=httpx.Response(200, json={
            "ready": False,
            "reason": "generation_service_unavailable",
        })
    )

    async with Nova3DClient(token=FAKE_TOKEN, base_url=BASE_URL) as client:
        with pytest.raises(Nova3DError, match="unavailable"):
            await client.generate(
                prompt="a robot",
                provider="google",
                llm="gemini-2.0-flash",
                api_key="AIza-test",
            )


@pytest.mark.asyncio
async def test_generate_credits_error(mock_api):
    mock_api.get("/workflow/readiness/sketch_to_3d").mock(
        return_value=httpx.Response(200, json=_readiness_ok())
    )
    mock_api.post("/run/state/sketch_to_3d").mock(
        return_value=httpx.Response(402, json={
            "code": "credits_or_user_key_required",
            "message": "Add credits or provide your own provider API key to generate.",
        })
    )

    async with Nova3DClient(token=FAKE_TOKEN, base_url=BASE_URL) as client:
        with pytest.raises(Nova3DCreditsError):
            await client.generate(
                prompt="a robot",
                provider="google",
                llm="gemini-2.0-flash",
                api_key="",
            )


@pytest.mark.asyncio
async def test_result_parsing_glb_url():
    result = GenerationResult.from_api(_result_ok(), WORKFLOW_ID)
    assert result.glb_url == "https://nova3d.xyz/assets/abc123.glb"
    assert result.joint_count == 1
    assert result.failed is False


@pytest.mark.asyncio
async def test_result_parsing_failure():
    data = {
        "sketch_to_3d_generator": [
            {
                "result": {
                    "status": "failed",
                    "error_category": "blender_generation_failed",
                    "user_message": "The script could not produce a valid model.",
                }
            }
        ]
    }
    result = GenerationResult.from_api(data, WORKFLOW_ID)
    assert result.failed is True
    assert result.glb_url is None
    assert "model" in result.error_message.lower()


def test_workflow_state_parse():
    assert WorkflowState.parse("completed").is_terminal is True
    assert WorkflowState.parse("succeeded").is_terminal is True
    assert WorkflowState.parse("running").is_terminal is False
    assert WorkflowState.parse("pending").is_terminal is False
    assert WorkflowState.parse("budget_exhausted").is_terminal is True
    assert WorkflowState.parse(None) == WorkflowState.UNKNOWN


def test_recoverable_errors():
    from nova3d_mcp.client import _is_recoverable
    assert _is_recoverable("workflow not found (404)") is True
    assert _is_recoverable("request failed (502)") is True
    assert _is_recoverable("still starting") is True
    assert _is_recoverable("sign in again") is False
    assert _is_recoverable("budget was exhausted") is False
    assert _is_recoverable("invalid api key") is False


from nova3d_mcp.client import _parse_auth_error


def test_parse_auth_error_revoked():
    resp = httpx.Response(401, json={
        "detail": {"code": "api_key_revoked", "message": "Key revoked."}
    })
    code, message = _parse_auth_error(resp)
    assert code == "api_key_revoked"
    assert "revoked" in message.lower()
    assert "nova3d.xyz" in message


def test_parse_auth_error_invalid_key():
    resp = httpx.Response(401, json={
        "detail": {"code": "invalid_api_key", "message": "Bad key."}
    })
    code, message = _parse_auth_error(resp)
    assert code == "invalid_api_key"
    assert "invalid" in message.lower()
    assert "nova3d.xyz" in message


def test_parse_auth_error_detail_string():
    resp = httpx.Response(401, json={"detail": "Not authenticated"})
    code, message = _parse_auth_error(resp)
    assert code is None
    assert message == "Not authenticated"


def test_parse_auth_error_no_json():
    resp = httpx.Response(401, content=b"Unauthorized")
    code, message = _parse_auth_error(resp)
    assert code is None
    assert "nova3d.xyz" in message


@pytest.mark.asyncio
async def test_generate_raises_auth_error_with_code(mock_api):
    mock_api.get("/workflow/readiness/sketch_to_3d").mock(
        return_value=httpx.Response(200, json=_readiness_ok())
    )
    mock_api.post("/run/state/sketch_to_3d").mock(
        return_value=httpx.Response(401, json={
            "detail": {"code": "api_key_revoked", "message": "Revoked."}
        })
    )
    async with Nova3DClient(token=FAKE_TOKEN, base_url=BASE_URL) as client:
        with pytest.raises(Nova3DAuthError, match="revoked"):
            await client.generate(
                prompt="a robot",
                provider="google",
                llm="gemini-2.0-flash",
                api_key="n3d_test",
            )


@pytest.mark.asyncio
async def test_get_me_success(mock_api):
    mock_api.get("/me").mock(
        return_value=httpx.Response(200, json={
            "user_id": "b333345d-a36c-487e-9096-5f7fd9a2901b",
            "email": "hassan@raresense.so",
            "available_credits": 1000,
            "tenant_id": "ten_e06a051bdb1f43b7b9d5bfaea1e07bf0",
        })
    )
    async with Nova3DClient(token=FAKE_TOKEN, base_url=BASE_URL) as client:
        me = await client.get_me()
    assert me["email"] == "hassan@raresense.so"
    assert me["available_credits"] == 1000


@pytest.mark.asyncio
async def test_get_me_invalid_key(mock_api):
    mock_api.get("/me").mock(
        return_value=httpx.Response(401, json={
            "detail": {"code": "invalid_api_key", "message": "Bad key."}
        })
    )
    async with Nova3DClient(token="n3d_bad", base_url=BASE_URL) as client:
        with pytest.raises(Nova3DAuthError, match="invalid"):
            await client.get_me()


@pytest.mark.asyncio
async def test_create_conversation_success(mock_api):
    mock_api.post("/conversations").mock(
        return_value=httpx.Response(201, json={
            "id": "conv-abc123",
            "tenant_id": "ten_abc",
            "user_id": "user-1",
            "source": "mcp",
            "kind": "generation",
            "status": "open",
            "title": "a toaster with removable tray",
            "external_conversation_id": None,
            "conversation_metadata": None,
            "created_at": "2026-05-30T12:00:00Z",
            "updated_at": "2026-05-30T12:00:00Z",
            "last_message_at": None,
        })
    )

    async with Nova3DClient(token=FAKE_TOKEN, base_url=BASE_URL) as client:
        conv_id = await client.create_conversation(title="a toaster with removable tray")

    assert conv_id == "conv-abc123"


@pytest.mark.asyncio
async def test_create_conversation_auth_error(mock_api):
    mock_api.post("/conversations").mock(
        return_value=httpx.Response(401, json={
            "detail": {"code": "invalid_api_key", "message": "Bad key."}
        })
    )

    async with Nova3DClient(token="n3d_bad", base_url=BASE_URL) as client:
        with pytest.raises(Nova3DAuthError):
            await client.create_conversation(title="a robot")


@pytest.mark.asyncio
async def test_create_conversation_missing_id_raises(mock_api):
    mock_api.post("/conversations").mock(
        return_value=httpx.Response(201, json={"source": "mcp", "kind": "generation"})
    )
    async with Nova3DClient(token=FAKE_TOKEN, base_url=BASE_URL) as client:
        with pytest.raises(Nova3DError, match="did not return an ID"):
            await client.create_conversation(title="a robot")


def test_result_parsing_api_key_source_present():
    data = {
        "sketch_to_3d_generator": [
            {
                "result": {
                    "model_url": "https://nova3d.xyz/assets/abc123.glb",
                    "model_artifact": {"url": "https://nova3d.xyz/assets/abc123.glb"},
                    "code_artifact": {"content": "import bpy"},
                    "api_key_source": "request",
                }
            }
        ]
    }
    result = GenerationResult.from_api(data, WORKFLOW_ID)
    assert result.api_key_source == "request"


def test_result_parsing_api_key_source_absent():
    result = GenerationResult.from_api(_result_ok(), WORKFLOW_ID)
    assert result.api_key_source is None


# ── Startup validation tests ──────────────────────────────────────────────────

from nova3d_mcp.server import _validate_startup


@pytest.mark.asyncio
async def test_validate_startup_no_token(monkeypatch, capsys):
    import nova3d_mcp.server as server_module
    server_module._startup_error = None
    monkeypatch.delenv("NOVA3D_TOKEN", raising=False)
    await _validate_startup()
    assert server_module._startup_error is not None
    assert "NOVA3D_TOKEN is not set" in server_module._startup_error
    captured = capsys.readouterr()
    assert "NOVA3D_TOKEN is not set" in captured.err
    server_module._startup_error = None


@pytest.mark.asyncio
async def test_validate_startup_success(mock_api, monkeypatch, capsys):
    monkeypatch.setenv("NOVA3D_TOKEN", "n3d_validkey")
    mock_api.get("/me").mock(
        return_value=httpx.Response(200, json={
            "user_id": "abc",
            "email": "test@example.com",
            "available_credits": 0,
            "tenant_id": "ten_abc",
        })
    )
    await _validate_startup()  # must not raise
    captured = capsys.readouterr()
    assert "test@example.com" in captured.err


@pytest.mark.asyncio
async def test_validate_startup_revoked_key(mock_api, monkeypatch, capsys):
    import nova3d_mcp.server as server_module
    server_module._startup_error = None
    monkeypatch.setenv("NOVA3D_TOKEN", "n3d_revoked")
    mock_api.get("/me").mock(
        return_value=httpx.Response(401, json={
            "detail": {"code": "api_key_revoked", "message": "Revoked."}
        })
    )
    await _validate_startup()
    assert server_module._startup_error is not None
    assert "revoked" in server_module._startup_error.lower()
    captured = capsys.readouterr()
    assert "revoked" in captured.err.lower()
    server_module._startup_error = None


@pytest.mark.asyncio
async def test_validate_startup_network_error(monkeypatch, capsys):
    import nova3d_mcp.server as server_module
    server_module._startup_error = None
    monkeypatch.setenv("NOVA3D_TOKEN", "n3d_testkey")
    with respx.mock(base_url=BASE_URL) as mock:
        mock.get("/me").mock(side_effect=httpx.NetworkError("Connection refused"))
        await _validate_startup()
    assert server_module._startup_error is not None
    assert "connection" in server_module._startup_error.lower() or "network" in server_module._startup_error.lower()
    captured = capsys.readouterr()
    assert "connection" in captured.err.lower() or "network" in captured.err.lower()
    server_module._startup_error = None


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
