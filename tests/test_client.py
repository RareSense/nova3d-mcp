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

from nova3d_mcp.client import Nova3DClient, Nova3DError, Nova3DCreditsError
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
