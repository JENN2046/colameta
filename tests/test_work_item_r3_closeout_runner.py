from __future__ import annotations

import json
import sys
from pathlib import Path

from runner.work_item_governance.canonical import sha256_file
from scripts.work_item_r3_closeout import (
    bundle_access_check,
    bundle_manifest,
    protected_assets_check,
    run_command,
)


def test_run_command_retains_exact_completed_process_record(tmp_path: Path) -> None:
    output = tmp_path / "command.json"

    result = run_command(
        name="full_pytest",
        output=output,
        command=[sys.executable, "-c", "print('1 passed')"],
    )

    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert result == 0
    assert evidence["argv"] == [sys.executable, "-c", "print('1 passed')"]
    assert evidence["exit_code"] == 0
    assert evidence["passed"] is True
    assert evidence["stdout"] == "1 passed\n"


def test_protected_asset_and_bundle_access_checks_fail_closed(
    tmp_path: Path,
    capsys,
) -> None:
    asset = tmp_path / "asset.txt"
    asset.write_text("protected", encoding="utf-8")
    assert protected_assets_check([f"{asset}={sha256_file(asset)}"]) == 0
    assert json.loads(capsys.readouterr().out)["pass"] is True

    assert bundle_access_check(bundle_root=tmp_path, required=["asset.txt", "missing.txt"]) == 1
    assert json.loads(capsys.readouterr().out)["pass"] is False


def test_bundle_manifest_excludes_itself_and_binds_file_list(tmp_path: Path) -> None:
    (tmp_path / "one.txt").write_text("one", encoding="utf-8")
    manifest_path = tmp_path / "MANIFEST.json"

    assert bundle_manifest(bundle_root=tmp_path, output=manifest_path) == 0

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["file_count"] == 1
    assert manifest["files"][0]["path"] == "one.txt"
