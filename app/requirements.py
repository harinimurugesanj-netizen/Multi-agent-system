"""Pure requirement logic (no LangGraph dependency, so it is trivially unit-testable)."""
from __future__ import annotations

from typing import Any, Mapping

from app.constants import ALLOWED, REQUIREMENT_FIELDS


def merge_requirements(
    current: Mapping[str, Any], extracted: Mapping[str, Any], overwrite: bool = True
) -> dict[str, Any]:
    """Return ONLY the requirement fields a node should write to state.

    - null/empty extracted values never erase an existing value.
    - a new non-null value replaces the old one (customer corrected themselves) when
      `overwrite` is True; otherwise it only fills gaps.
    Raw, possibly invalid, values are kept so the validator can report them.
    """
    updates: dict[str, Any] = {}
    for field in REQUIREMENT_FIELDS:
        new = extracted.get(field)
        if new is None or (isinstance(new, str) and not new.strip()):
            continue
        if overwrite or current.get(field) is None:
            updates[field] = new
    return updates


def validate_requirements(state: Mapping[str, Any]) -> dict[str, Any]:
    """Check all three fields; returns the state update for the validation node."""
    missing: list[str] = []
    invalid: dict[str, str] = {}
    for field in REQUIREMENT_FIELDS:
        value = state.get(field)
        if value is None:
            missing.append(field)
        elif value not in ALLOWED[field]:
            invalid[field] = str(value)
    status = "invalid" if invalid else "missing" if missing else "valid"
    return {"missing_fields": missing, "invalid_fields": invalid, "validation_status": status}
