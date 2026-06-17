import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from typing import Any


def now_iso() -> str:
    """Return the canonical Runner ISO timestamp with local timezone offset."""
    return datetime.now(timezone.utc).astimezone().isoformat()


def write_json_atomic(path: str, payload: dict[str, Any]) -> None:
    """Atomically write *payload* as pretty-printed JSON to *path*.

    Uses a temporary file in the same directory then ``os.replace`` so that
    readers never see a partial write.  Parent directories are created
    automatically.  Raises on any I/O error after cleaning up the temp file.
    """
    dir_name = os.path.dirname(path) or "."
    os.makedirs(dir_name, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp-runner-", suffix=".json", dir=dir_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def run_git(args: list[str], cwd: str, *, timeout: int = 30) -> tuple[int, str, str]:
    """Run a git subprocess and return ``(returncode, stdout, stderr)``.

    On ``FileNotFoundError`` (git not installed) returns ``(127, "", msg)``.
    On any other exception returns ``(1, "", msg)``.
    """
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError:
        return 127, "", "git 命令不可用"
    except Exception as exc:
        return 1, "", str(exc)
