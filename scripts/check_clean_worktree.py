from __future__ import annotations

import subprocess
import sys


def main() -> int:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            shell=False,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        print("Unable to inspect Git worktree state.", file=sys.stderr)
        return 2

    if result.returncode != 0:
        print("Unable to inspect Git worktree state.", file=sys.stderr)
        return 2
    if result.stdout:
        print("Git worktree is not clean.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
