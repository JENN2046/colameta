from __future__ import annotations

import argparse
import json
import os
import subprocess  # nosec B404
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runner.work_item_governance.canonical import canonical_json, canonical_sha256, sha256_file
from runner.work_item_governance.closeout import verify_r2_closeout_receipt
from runner.work_item_governance.source_binding import verify_runtime_source_artifacts


COMMAND_EVIDENCE_SCHEMA = "work_item_closeout_command_evidence.v1"


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    target = path.expanduser().resolve()
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(canonical_json(payload))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, target)
        os.chmod(target, 0o600)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def run_command(*, name: str, output: Path, command: list[str]) -> int:
    if not command:
        raise ValueError("command argv is required")
    started_at = _timestamp()
    completed = subprocess.run(  # nosec B603
        command,
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
        timeout=900,
    )
    ended_at = _timestamp()
    evidence = {
        "schema_version": COMMAND_EVIDENCE_SCHEMA,
        "name": name,
        "argv": command,
        "cwd": Path.cwd().resolve().as_posix(),
        "started_at": started_at,
        "ended_at": ended_at,
        "exit_code": completed.returncode,
        "passed": completed.returncode == 0,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    _write_json(output, evidence)
    return completed.returncode


def protected_assets_check(expected: list[str]) -> int:
    records: list[dict[str, Any]] = []
    passed = True
    for item in expected:
        path_text, separator, expected_sha256 = item.rpartition("=")
        path = Path(path_text)
        valid = bool(separator and path.is_file() and sha256_file(path) == expected_sha256)
        passed = passed and valid
        records.append(
            {
                "path": path_text,
                "expected_sha256": expected_sha256,
                "actual_sha256": sha256_file(path) if path.is_file() else None,
                "match": valid,
            }
        )
    print(canonical_json({"pass": passed, "assets": records}))
    return 0 if passed else 1


def bundle_access_check(*, bundle_root: Path, required: list[str]) -> int:
    root = bundle_root.expanduser().resolve()
    records: list[dict[str, Any]] = []
    passed = True
    for relative_text in required:
        target = (root / relative_text).resolve()
        try:
            target.relative_to(root)
            within_root = True
        except ValueError:
            within_root = False
        valid = within_root and target.is_file() and target.stat().st_size > 0
        passed = passed and valid
        records.append(
            {
                "path": relative_text,
                "readable": valid,
                "sha256": sha256_file(target) if valid else None,
            }
        )
    print(canonical_json({"pass": passed, "files": records}))
    return 0 if passed else 1


def wheel_inventory(*, checkout: Path, wheel: Path, output: Path) -> int:
    measured = verify_runtime_source_artifacts(
        checkout_root=checkout,
        wheel_artifact=wheel,
    )
    payload = {
        "schema_version": "work_item_runtime_wheel_inventory.v1",
        "source_binding": measured.source_binding,
        "file_manifest_digest": measured.file_manifest_digest,
        "wheel_sha256": sha256_file(wheel),
        "wheel_size_bytes": wheel.stat().st_size,
        "verified": True,
    }
    _write_json(output, payload)
    return 0


def bundle_manifest(*, bundle_root: Path, output: Path) -> int:
    root = bundle_root.expanduser().resolve()
    target = output.expanduser().resolve()
    files: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.resolve() == target:
            continue
        relative = path.relative_to(root).as_posix()
        files.append(
            {
                "path": relative,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    payload = {
        "schema_version": "work_item_r3_closeout_bundle_manifest.v1",
        "generated_at": _timestamp(),
        "files": files,
        "file_count": len(files),
        "file_list_root_sha256": canonical_sha256(files),
    }
    _write_json(target, payload)
    return 0


def verify_receipt(*, receipt: Path, bundle_root: Path, project_root: Path) -> int:
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    result = verify_r2_closeout_receipt(
        payload,
        evidence_root=bundle_root,
        project_root=project_root,
    )
    print(canonical_json({"pass": bool(1), "verification": result}))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="action", required=True)
    run = commands.add_parser("run-command")
    run.add_argument("--name", required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("command", nargs=argparse.REMAINDER)
    protected = commands.add_parser("protected-assets-check")
    protected.add_argument("--expected", action="append", default=[])
    access = commands.add_parser("bundle-access-check")
    access.add_argument("--bundle-root", type=Path, required=True)
    access.add_argument("--required", action="append", default=[])
    inventory = commands.add_parser("wheel-inventory")
    inventory.add_argument("--checkout", type=Path, required=True)
    inventory.add_argument("--wheel", type=Path, required=True)
    inventory.add_argument("--output", type=Path, required=True)
    manifest = commands.add_parser("bundle-manifest")
    manifest.add_argument("--bundle-root", type=Path, required=True)
    manifest.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser("verify-receipt")
    verify.add_argument("--receipt", type=Path, required=True)
    verify.add_argument("--bundle-root", type=Path, required=True)
    verify.add_argument("--project-root", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.action == "run-command":
        command = list(arguments.command)
        if command[:1] == ["--"]:
            command = command[1:]
        return run_command(name=arguments.name, output=arguments.output, command=command)
    if arguments.action == "protected-assets-check":
        return protected_assets_check(arguments.expected)
    if arguments.action == "bundle-access-check":
        return bundle_access_check(bundle_root=arguments.bundle_root, required=arguments.required)
    if arguments.action == "wheel-inventory":
        return wheel_inventory(
            checkout=arguments.checkout,
            wheel=arguments.wheel,
            output=arguments.output,
        )
    if arguments.action == "bundle-manifest":
        return bundle_manifest(bundle_root=arguments.bundle_root, output=arguments.output)
    if arguments.action == "verify-receipt":
        return verify_receipt(
            receipt=arguments.receipt,
            bundle_root=arguments.bundle_root,
            project_root=arguments.project_root,
        )
    raise AssertionError("unreachable")


if __name__ == "__main__":
    sys.exit(main())
