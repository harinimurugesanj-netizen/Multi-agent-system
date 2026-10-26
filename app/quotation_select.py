"""Helpers for picking which previous quotation the customer means (no word lists)."""
import re
from datetime import datetime
from typing import Any, Optional

from app.extraction import parse_llm_json

_ONLY_NUMBER = re.compile(r"^\W*(?:no\.?|number|option|#)?\s*(\d{1,2})\W*$", re.I)

PICK_PROMPT = """
The customer was asked which of their quotations they mean.
Quotations (newest first):
{list}
Customer's reply: {reply}
Reply with ONE JSON object: {"choice": <number of the quotation they mean, or null if it is unclear>}
JSON:"""


def record_to_candidate(rec) -> dict[str, Any]:
    """QuotationRecord -> plain, serialisable dict (safe for graph state)."""
    return {
        "id": rec.id, "created_at": rec.created_at.isoformat(), "frame_size": rec.frame_size,
        "frame_material": rec.frame_material, "glass_type": rec.glass_type,
        "selling_price": str(rec.selling_price), "revision_number": rec.revision_number,
        "original_quotation_id": rec.original_quotation_id,
    }


def choose_quotation(candidates: list[dict], latest: bool) -> Optional[str]:
    """Automatic choice, or None if ambiguous. `latest` comes from the LLM (evidence-checked)."""
    if not candidates:
        return None
    if len(candidates) == 1 or latest:
        return candidates[0]["id"]            # candidates are newest-first
    return None


def format_candidates(candidates: list[dict], currency: str = "") -> str:
    from app.formatting import describe_items, fmt_money
    lines = []
    for i, c in enumerate(candidates, 1):
        day = datetime.fromisoformat(c["created_at"]).strftime("%d %b %Y")
        lines.append(f"{i}. {describe_items(c['frame_size'], c['frame_material'], c['glass_type'])}"
                     f" - {fmt_money(c['selling_price'], currency)} ({day})")
    return "\n".join(lines)


def resolve_reply(llm, candidates: list[dict], reply: str, currency: str = "") -> Optional[str]:
    """A bare number is taken directly; anything else the LLM interprets, and its answer is
    accepted only if it is a valid index into the list."""
    m = _ONLY_NUMBER.match(reply or "")
    if m:
        idx = int(m.group(1))
        return candidates[idx - 1]["id"] if 1 <= idx <= len(candidates) else None
    prompt = (PICK_PROMPT.replace("{list}", format_candidates(candidates, currency))
              .replace("{reply}", reply or ""))
    try:
        choice = parse_llm_json(llm.invoke(prompt).content).get("choice")
    except Exception:
        return None
    if isinstance(choice, int) and not isinstance(choice, bool) and 1 <= choice <= len(candidates):
        return candidates[choice - 1]["id"]
    return None