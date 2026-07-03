from pathlib import Path
import unittest

from runner.mcp_server import (
    COMMANDER_APP_WIDGET_MIME_TYPE,
    COMMANDER_APP_WIDGET_URI,
    MCPPlanningBridgeServer,
)


ROOT = Path(__file__).resolve().parents[1]


class MCPJsonrpcNotificationsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = MCPPlanningBridgeServer(str(ROOT))

    def test_jsonrpc_notification_does_not_emit_response(self) -> None:
        response = self.server._handle_jsonrpc_request(
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
        )

        self.assertIsNone(response)

    def test_initialized_request_with_id_keeps_legacy_response(self) -> None:
        response = self.server._handle_jsonrpc_request(
            {"jsonrpc": "2.0", "id": 1, "method": "notifications/initialized", "params": {}}
        )

        self.assertEqual(response, {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}})

    def test_initialize_advertises_tools_and_resources(self) -> None:
        response = self.server._handle_jsonrpc_request(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        )

        capabilities = response["result"]["capabilities"]
        self.assertFalse(capabilities["tools"]["listChanged"])
        self.assertFalse(capabilities["resources"]["subscribe"])
        self.assertFalse(capabilities["resources"]["listChanged"])

    def test_commander_app_resource_can_be_listed_and_read(self) -> None:
        listed = self.server._handle_jsonrpc_request(
            {"jsonrpc": "2.0", "id": 1, "method": "resources/list", "params": {}}
        )
        resource = listed["result"]["resources"][0]

        self.assertEqual(resource["uri"], COMMANDER_APP_WIDGET_URI)
        self.assertEqual(resource["mimeType"], COMMANDER_APP_WIDGET_MIME_TYPE)
        self.assertEqual(resource["_meta"]["ui"]["csp"]["connectDomains"], [])

        read = self.server._handle_jsonrpc_request(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "resources/read",
                "params": {"uri": COMMANDER_APP_WIDGET_URI},
            }
        )
        content = read["result"]["contents"][0]

        self.assertEqual(content["uri"], COMMANDER_APP_WIDGET_URI)
        self.assertEqual(content["mimeType"], COMMANDER_APP_WIDGET_MIME_TYPE)
        self.assertIn("ColaMeta Commander", content["text"])
        self.assertTrue(content["_meta"]["openai/widgetDescription"])

    def test_render_commander_app_tool_descriptor_and_call_attach_widget_meta(self) -> None:
        listed = self.server._handle_jsonrpc_request(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        )
        tools = {item["name"]: item for item in listed["result"]["tools"]}
        render_tool = tools["render_commander_app"]

        self.assertTrue(render_tool["annotations"]["readOnlyHint"])
        self.assertEqual(render_tool["_meta"]["ui"]["resourceUri"], COMMANDER_APP_WIDGET_URI)
        self.assertEqual(render_tool["_meta"]["openai/outputTemplate"], COMMANDER_APP_WIDGET_URI)

        called = self.server._handle_jsonrpc_request(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "render_commander_app", "arguments": {}},
            }
        )
        result = called["result"]
        data = result["structuredContent"]["data"]

        self.assertEqual(result["_meta"]["ui"]["resourceUri"], COMMANDER_APP_WIDGET_URI)
        self.assertNotIn("_meta", result["structuredContent"])
        self.assertEqual(data["app_manifest_version"], "colameta_commander_app.v1")
        self.assertEqual(data["app"]["resource_methods"], ["resources/list", "resources/read"])
        self.assertTrue(data["authority_boundary"]["does_not_authorize_commit_or_push"])


if __name__ == "__main__":
    unittest.main()
