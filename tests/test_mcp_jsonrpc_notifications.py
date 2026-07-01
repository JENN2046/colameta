from pathlib import Path

from runner.mcp_server import MCPPlanningBridgeServer


ROOT = Path(__file__).resolve().parents[1]


def test_jsonrpc_notification_does_not_emit_response() -> None:
    server = MCPPlanningBridgeServer(str(ROOT))

    response = server._handle_jsonrpc_request(
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
    )

    assert response is None


def test_initialized_request_with_id_keeps_legacy_response() -> None:
    server = MCPPlanningBridgeServer(str(ROOT))

    response = server._handle_jsonrpc_request(
        {"jsonrpc": "2.0", "id": 1, "method": "notifications/initialized", "params": {}}
    )

    assert response == {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}
