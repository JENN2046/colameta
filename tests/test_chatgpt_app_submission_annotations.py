from runner.mcp_server import MCPPlanningBridgeServer


REQUIRED_ANNOTATIONS = ("readOnlyHint", "openWorldHint", "destructiveHint")


def test_normal_profile_tools_declare_required_chatgpt_submission_annotations(tmp_path):
    server = MCPPlanningBridgeServer(str(tmp_path), service_mode=True, exposure_profile="normal")

    for tool in server._filter_tools_by_exposure_profile(server.tool_defs):
        assert isinstance(tool.annotations, dict), tool.name
        for key in REQUIRED_ANNOTATIONS:
            assert isinstance(tool.annotations.get(key), bool), (tool.name, key)


def test_mixed_behavior_submission_annotations_match_real_side_effect_boundaries(tmp_path):
    server = MCPPlanningBridgeServer(str(tmp_path), service_mode=True, exposure_profile="normal")
    tools = {tool.name: tool for tool in server._filter_tools_by_exposure_profile(server.tool_defs)}

    assert tools["list_registered_projects"].annotations == {
        "readOnlyHint": True,
        "openWorldHint": False,
        "destructiveHint": False,
    }
    assert tools["manage_git"].annotations == {
        "readOnlyHint": False,
        "openWorldHint": True,
        "destructiveHint": True,
    }
    assert tools["manage_files"].annotations == {
        "readOnlyHint": False,
        "openWorldHint": False,
        "destructiveHint": True,
    }
    assert tools["manage_validation_run"].annotations == {
        "readOnlyHint": False,
        "openWorldHint": False,
        "destructiveHint": False,
    }
