from __future__ import annotations

from scripts import self_hosting_smoke


def test_pyproject_fallback_reads_multiline_dependencies(tmp_path, monkeypatch) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "colameta"
version = "0.1.2"
description = "AI coding workflow harness connecting GPTs to local executors"
requires-python = ">=3.10"
license = {text = "禁止商业使用"}
classifiers = [
    "Development Status :: 3 - Alpha",
]
dependencies = [
    "PyJWT[crypto]>=2.8,<3",
]

[project.scripts]
colameta = "scripts.runner_cli:main"
""".lstrip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(self_hosting_smoke, "ROOT", tmp_path)
    monkeypatch.setattr(self_hosting_smoke, "tomllib", None)

    metadata = self_hosting_smoke._read_pyproject_metadata()

    assert metadata["license"] == {"text": "禁止商业使用"}
    assert metadata["classifiers"] == ["Development Status :: 3 - Alpha"]
    assert metadata["dependencies"] == ["PyJWT[crypto]>=2.8,<3"]
    assert metadata["scripts"] == {"colameta": "scripts.runner_cli:main"}
    assert self_hosting_smoke._project_dependencies() == ["PyJWT[crypto]>=2.8,<3"]


def test_toml_literal_fallback_reads_empty_inline_table() -> None:
    assert self_hosting_smoke._literal_toml_value("{}") == {}
