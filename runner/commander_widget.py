"""Packaged Commander widget resource for the ChatGPT App surface."""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files


COMMANDER_WIDGET_RESOURCE_NAME = "commander_widget.html"


@lru_cache(maxsize=1)
def commander_widget_html() -> str:
    """Return the versioned Commander HTML payload from installed package data.

    The legacy inline literal had no terminal newline. Keep that response byte
    contract while storing the packaged text file with a normal final newline.
    """

    payload = files("runner").joinpath(COMMANDER_WIDGET_RESOURCE_NAME).read_text(encoding="utf-8")
    return payload.removesuffix("\n")
