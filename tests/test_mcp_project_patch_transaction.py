from __future__ import annotations

from pathlib import Path

from runner.file_transaction import FileTransaction
from runner.mcp_project_patch import MCPProjectPatchManager
from runner.source_review_bridge import SourceReviewBridge


def _manager(project: Path) -> MCPProjectPatchManager:
    return MCPProjectPatchManager(str(project), SourceReviewBridge())


def test_project_patch_apply_returns_transaction_receipt(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    source_dir = project / "src"
    source_dir.mkdir(parents=True)
    target = source_dir / "app.py"
    target.write_text("value = 'old'\n", encoding="utf-8")

    manager = _manager(project)
    preview = manager.preview(
        {
            "file": "src/app.py",
            "old_text": "old",
            "new_text": "new",
            "reason": "test transaction receipt",
        }
    )
    assert preview["ok"] is True

    result = manager.apply({"preview_id": preview["preview_id"], "reason": "accepted"})

    assert result["ok"] is True
    assert target.read_text(encoding="utf-8") == "value = 'new'\n"
    receipt = result["transaction_receipt"]
    assert receipt["status"] == "committed"
    assert receipt["label"] == "manage_project_patch.apply"
    assert receipt["operation_count"] == 1
    assert receipt["applied_count"] == 1
    assert receipt["paths"] == ["src/app.py"]
    assert receipt["content_included"] is False


def test_project_patch_apply_rolls_back_partial_transaction(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "repo"
    source_dir = project / "src"
    source_dir.mkdir(parents=True)
    first = source_dir / "a.py"
    second = source_dir / "b.py"
    first.write_text("ONE\n", encoding="utf-8")
    second.write_text("ALPHA\n", encoding="utf-8")
    patch_text = """diff --git a/src/a.py b/src/a.py
--- a/src/a.py
+++ b/src/a.py
@@ -1 +1 @@
-ONE
+TWO
diff --git a/src/b.py b/src/b.py
--- a/src/b.py
+++ b/src/b.py
@@ -1 +1 @@
-ALPHA
+BETA
"""

    manager = _manager(project)
    preview = manager.preview({"patch_text": patch_text, "reason": "test rollback"})
    assert preview["ok"] is True
    original_write = FileTransaction._atomic_write_text

    def fail_on_second_write(self: FileTransaction, path: Path, content: str) -> None:
        if path.name == "b.py" and content == "BETA\n":
            raise OSError("synthetic write failure")
        original_write(self, path, content)

    monkeypatch.setattr(FileTransaction, "_atomic_write_text", fail_on_second_write)

    result = manager.apply({"preview_id": preview["preview_id"], "reason": "accepted"})

    assert result["ok"] is False
    assert result["error_code"] == "PATCH_TRANSACTION_FAILED"
    assert first.read_text(encoding="utf-8") == "ONE\n"
    assert second.read_text(encoding="utf-8") == "ALPHA\n"
    receipt = result["transaction_receipt"]
    assert receipt["status"] == "rolled_back"
    assert receipt["error_code"] == "FILE_TRANSACTION_APPLY_FAILED"
    assert receipt["operation_count"] == 2
    assert receipt["applied_count"] == 1
    assert receipt["content_included"] is False
