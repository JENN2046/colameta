from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runner.chatgpt_development_acceptance import (  # noqa: E402
    ChatGPTDevelopmentContractRehearsalError,
    run_chatgpt_development_contract_rehearsal,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the local ChatGPT Commander contract rehearsal. "
            "A passing result is developer preflight only, not live ChatGPT acceptance or release authority."
        )
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Compatibility flag; output is always JSON.",
    )
    parser.parse_args(argv)

    try:
        result = run_chatgpt_development_contract_rehearsal()
    except ChatGPTDevelopmentContractRehearsalError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
