"""Pure helpers for picking which previous quotation the customer means."""
import re
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from app.constants import REQUIREMENT_FIELDS
from app.extraction import _found_in_text

_RECENCY = re.compile(r"\b(previous|last|latest|recent|newest)\b", re.I)
_ONLY_NUMBER = re.compile(r"^\W*(?:no\.?|number|option|#)?\s*(\d{1,2})\W*$", re.I)


def has_recency_word(text: str) -> bool:
    return bool(_RECENCY.search(text or ""))


def record_to_candidate(rec) -> dict[str, Any]:
    """QuotationRecord -> plain, serialisable dict (safe for graph state)."""
    return {
        "id": rec.id, "created_at": rec.created_at.isoformat(), "frame_size": rec.frame_size,
        "frame_material": rec.frame_material, "glass_type": rec.glass_type,
        "selling_price": str(rec.selling_price), "revision_number": rec.revision_number,
        "original_quotation_id": rec.original_quotation_id,
    }


def choose_quotation(candidates: list[dict], text: str) -> Optional[str]:
    """Automatic choice from the customer's first message, or None if ambiguous."""
    if not candidates:
        return None
    if len(candidates) == 1 or has_recency_word(text):
        return candidates[0]["id"]          # candidates are newest-first
    return None


def resolve_reply(candidates: list[dict], reply: str) -> Optional[str]:
    """Interpret the customer's answer to 'which quotation?'. Conservative: None if unclear."""
    m = _ONLY_NUMBER.match(reply or "")
    if m:
        idx = int(m.group(1))
        return candidates[idx - 1]["id"] if 1 <= idx <= len(candidates) else None
    if has_recency_word(reply):
        return candidates[0]["id"]
    matches = candidates
    mentioned = False
    for f in REQUIREMENT_FIELDS:
        found = _found_in_text(f, reply or "")
        if found:
            mentioned = True
            matches = [c for c in matches if c[f] in found]
    return matches[0]["id"] if mentioned and len(matches) == 1 else None


def format_candidates(candidates: list[dict], currency: str = "") -> str:
    from app.formatting import describe_items, fmt_money
    lines = []
    for i, c in enumerate(candidates, 1):
        day = datetime.fromisoformat(c["created_at"]).strftime("%d %b %Y")
        lines.append(f"{i}. {describe_items(c['frame_size'], c['frame_material'], c['glass_type'])}"
                     f" - {fmt_money(c['selling_price'], currency)} ({day})")
    return "\n".join(lines)
