"""Pure requirement logic. The DATABASE CATALOG decides what is valid (no hardcoded options)."""
from typing import Any, Mapping

from app.constants import REQUIREMENT_FIELDS
from app.options import join_options, show

_NOUN = {"frame_size": ("frame size", "frame sizes"),
         "frame_material": ("frame material", "frame materials"),
         "glass_type": ("glass type", "glass types")}


def merge_requirements(current: Mapping[str, Any], extracted: Mapping[str, Any],
                       overwrite: bool = True) -> dict[str, Any]:
    """Return ONLY the fields to write. A null/empty value never erases an existing value."""
    updates: dict[str, Any] = {}
    for f in REQUIREMENT_FIELDS:
        new = extracted.get(f)
        if new is None or (isinstance(new, str) and not new.strip()):
            continue
        if overwrite or current.get(f) is None:
            updates[f] = new
    return updates


def validate_against_catalog(values: Mapping[str, Any], catalog: Mapping[str, Any]) -> dict[str, Any]:
    """Check the three requirements against what the database offers.

    Detects: missing fields, values that are not offered, and size/material or size/glass
    combinations with no price row. `problems` are plain-English sentences that are shown to
    the customer AND given to the LLM when it repairs its JSON.
    """
    missing: list[str] = []
    invalid: dict[str, str] = {}
    problems: list[str] = []

    for f in REQUIREMENT_FIELDS:
        v = values.get(f)
        if v is None:
            missing.append(f)
        elif v not in catalog.get(f, []):
            invalid[f] = str(v)
            singular, plural = _NOUN[f]
            problems.append(f'The {singular} "{show(f, str(v))}" is not available. '
                            f"Available {plural}: {join_options(f, catalog.get(f, []))}.")

    size, mat, glass = values.get("frame_size"), values.get("frame_material"), values.get("glass_type")
    if size in catalog.get("frame_size", []):
        size_s = show("frame_size", size)
        if mat in catalog.get("frame_material", []) and [size, mat] not in catalog.get("frame_combos", []):
            invalid["frame_material"] = mat
            options = sorted({m for s, m in catalog.get("frame_combos", []) if s == size})
            problems.append(f"{mat.capitalize()} frames are not available in {size_s}. "
                            + (f"Available materials for {size_s}: {join_options('frame_material', options)}."
                               if options else f"No frame materials are available for {size_s}."))
        if glass in catalog.get("glass_type", []) and [size, glass] not in catalog.get("glass_combos", []):
            invalid["glass_type"] = glass
            options = sorted({g for s, g in catalog.get("glass_combos", []) if s == size})
            problems.append(f"{glass.capitalize()} glass is not available for {size_s}. "
                            + (f"Available glass types for {size_s}: {join_options('glass_type', options)}."
                               if options else f"No glass types are available for {size_s}."))

    status = "invalid" if invalid else "missing" if missing else "valid"
    return {"missing_fields": missing, "invalid_fields": invalid, "problems": problems,
            "validation_status": status}