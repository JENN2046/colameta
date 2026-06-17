from typing import Literal

CommandStatus = Literal[
    "NOT_RUN",
    "RUNNING",
    "PASSED",
    "FAILED",
    "SKIPPED",
]
