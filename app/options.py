"""Small helpers that turn the database catalog into text (for prompts and customer messages)."""
from typing import Mapping, Sequence

from app.constants import REQUIREMENT_FIELDS


def show(field: str, value: str) -> str:
    return value.replace("x", "×") if field == "frame_size" else value


def join_options(field: str, values: Sequence[str]) -> str:
    items = [show(field, v) for v in values]
    if not items:
        return "none"
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " or " + items[-1]


def options_text(catalog: Mapping) -> str:
    """The options currently offered (read from the database), one line per field."""
    return "\n".join(f"{f}: {', '.join(catalog.get(f, []))}" for f in REQUIREMENT_FIELDS)