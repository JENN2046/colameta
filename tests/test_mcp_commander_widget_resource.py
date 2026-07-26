from importlib.resources import files

from runner.commander_widget import COMMANDER_WIDGET_RESOURCE_NAME, commander_widget_html
from runner.mcp_server import MCPPlanningBridgeServer


def test_commander_widget_is_loaded_from_packaged_resource() -> None:
    resource_text = files("runner").joinpath(COMMANDER_WIDGET_RESOURCE_NAME).read_text(encoding="utf-8")

    assert commander_widget_html() == resource_text.removesuffix("\n")
    assert not commander_widget_html().endswith("\n")
    assert "ColaMeta Commander" in resource_text
    assert "window.openai.callTool" in resource_text


def test_server_widget_reader_delegates_to_packaged_resource() -> None:
    assert MCPPlanningBridgeServer._commander_widget_html(object()) == commander_widget_html()
