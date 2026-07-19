from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLISH_WORKFLOW = ROOT / ".github" / "workflows" / "publish.yml"


def _workflow_text() -> str:
    return PUBLISH_WORKFLOW.read_text(encoding="utf-8")


def test_private_beta_tags_do_not_trigger_pypi_publish() -> None:
    workflow = _workflow_text()

    include_pattern = '      - "v*"'
    exclude_pattern = '      - "!v*-private-beta.*"'
    assert include_pattern in workflow
    assert exclude_pattern in workflow
    assert workflow.index(include_pattern) < workflow.index(exclude_pattern)


def test_fork_cannot_publish_the_upstream_pypi_project() -> None:
    workflow = _workflow_text()

    assert "if: github.repository == 'riccilnl/colameta'" in workflow
