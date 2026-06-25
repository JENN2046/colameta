from __future__ import annotations

import importlib.util
import os
import ast
import base64
import hashlib
import subprocess
import sys
import tempfile
import venv
import zipfile
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    tomllib = None


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_IMPORTS = ("runner", "adapters", "schemas", "scripts")
DIST_INFO_PACKAGE_ROOTS = PACKAGE_IMPORTS


def venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def venv_script(venv_dir: Path, name: str) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / f"{name}.exe"
    return venv_dir / "bin" / name


def run(command: list[str | os.PathLike[str]], *, cwd: Path = ROOT) -> None:
    printable = " ".join(str(part) for part in command)
    print(f"+ {printable}")
    subprocess.run([str(part) for part in command], cwd=cwd, check=True)


def has_module(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def current_python_can_build_wheels() -> bool:
    return all(has_module(name) for name in ("pip", "setuptools", "wheel"))


def create_venv(path: Path, *, system_site_packages: bool = False) -> Path:
    venv.EnvBuilder(with_pip=True, system_site_packages=system_site_packages).create(path)
    return venv_python(path)


def select_builder_python(temp_dir: Path) -> Path | None:
    if current_python_can_build_wheels():
        return Path(sys.executable)

    builder_dir = temp_dir / "builder-venv"
    builder_python = create_venv(builder_dir, system_site_packages=True)
    probe = subprocess.run(
        [
            str(builder_python),
            "-c",
            "import pip, setuptools, wheel",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if probe.returncode == 0:
        return builder_python

    print("pip wheel builder dependencies are unavailable; using stdlib wheel fallback.", file=sys.stderr)
    print('Install the test extra for the standard path: python -m pip install -e ".[test]"', file=sys.stderr)
    return None


def _read_pyproject_metadata() -> dict[str, Any]:
    pyproject_path = ROOT / "pyproject.toml"
    if tomllib is not None:
        with pyproject_path.open("rb") as handle:
            return tomllib.load(handle)["project"]

    project: dict[str, Any] = {}
    scripts: dict[str, str] = {}
    section = ""
    for raw_line in pyproject_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line.strip("[]")
            continue
        if "=" not in line:
            continue
        key, raw_value = [part.strip() for part in line.split("=", 1)]
        if section == "project.scripts":
            scripts[key] = ast.literal_eval(raw_value)
        elif section == "project" and key in {"name", "version", "description", "requires-python"}:
            project[key] = ast.literal_eval(raw_value)
    project["scripts"] = scripts
    return project


def _iter_package_files() -> list[Path]:
    files: list[Path] = []
    for package_root in DIST_INFO_PACKAGE_ROOTS:
        root = ROOT / package_root
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
                continue
            files.append(path)
    return files


def _wheel_record_hash(data: bytes) -> str:
    digest = hashlib.sha256(data).digest()
    return "sha256=" + base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _metadata_text(project: dict[str, Any]) -> str:
    lines = [
        "Metadata-Version: 2.1",
        f"Name: {project['name']}",
        f"Version: {project['version']}",
    ]
    if project.get("description"):
        lines.append(f"Summary: {project['description']}")
    if project.get("requires-python"):
        lines.append(f"Requires-Python: {project['requires-python']}")
    license_info = project.get("license")
    if isinstance(license_info, dict) and license_info.get("text"):
        lines.append(f"License: {license_info['text']}")
    for classifier in project.get("classifiers", []):
        lines.append(f"Classifier: {classifier}")
    return "\n".join(lines) + "\n"


def build_stdlib_wheel(wheelhouse: Path) -> None:
    project = _read_pyproject_metadata()
    distribution = str(project["name"]).replace("-", "_")
    version = str(project["version"])
    dist_info = f"{distribution}-{version}.dist-info"
    wheel_name = f"{distribution}-{version}-py3-none-any.whl"
    wheel_path = wheelhouse / wheel_name

    archive_entries: dict[str, bytes] = {}
    for path in _iter_package_files():
        archive_entries[path.relative_to(ROOT).as_posix()] = path.read_bytes()

    archive_entries[f"{dist_info}/METADATA"] = _metadata_text(project).encode("utf-8")
    archive_entries[f"{dist_info}/WHEEL"] = (
        "Wheel-Version: 1.0\n"
        "Generator: colameta-self-hosting-smoke\n"
        "Root-Is-Purelib: true\n"
        "Tag: py3-none-any\n"
    ).encode("utf-8")
    archive_entries[f"{dist_info}/top_level.txt"] = ("\n".join(DIST_INFO_PACKAGE_ROOTS) + "\n").encode("utf-8")

    scripts = project.get("scripts", {})
    if scripts:
        lines = ["[console_scripts]"]
        lines.extend(f"{name} = {target}" for name, target in sorted(scripts.items()))
        archive_entries[f"{dist_info}/entry_points.txt"] = ("\n".join(lines) + "\n").encode("utf-8")

    record_path = f"{dist_info}/RECORD"
    record_lines = [
        f"{name},{_wheel_record_hash(data)},{len(data)}"
        for name, data in sorted(archive_entries.items())
    ]
    record_lines.append(f"{record_path},,")
    archive_entries[record_path] = ("\n".join(record_lines) + "\n").encode("utf-8")

    with zipfile.ZipFile(wheel_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(archive_entries.items()):
            archive.writestr(name, data)
    print(f"+ stdlib wheel fallback wrote {wheel_path}")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="colameta-smoke-") as temp_name:
        temp_dir = Path(temp_name)
        wheelhouse = temp_dir / "wheelhouse"
        wheelhouse.mkdir()

        builder_python = select_builder_python(temp_dir)
        if builder_python is None:
            build_stdlib_wheel(wheelhouse)
        else:
            run(
                [
                    builder_python,
                    "-m",
                    "pip",
                    "wheel",
                    "--no-index",
                    "--no-deps",
                    "--no-build-isolation",
                    "--wheel-dir",
                    wheelhouse,
                    ROOT,
                ]
            )

        wheels = sorted(wheelhouse.glob("colameta-*.whl"))
        if len(wheels) != 1:
            print(f"expected exactly one colameta wheel, found {len(wheels)}", file=sys.stderr)
            return 1

        runtime_dir = temp_dir / "runtime-venv"
        runtime_python = create_venv(runtime_dir)
        run(
            [
                runtime_python,
                "-m",
                "pip",
                "install",
                "--no-index",
                "--find-links",
                wheelhouse,
                "colameta",
            ]
        )

        import_script = "; ".join(f"import {name}" for name in PACKAGE_IMPORTS)
        run([runtime_python, "-c", import_script])
        run([venv_script(runtime_dir, "colameta"), "help"])

    print("self-hosting smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
