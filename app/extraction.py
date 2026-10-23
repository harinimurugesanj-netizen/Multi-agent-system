"""Stage 2a: Qwen3 requirement extraction with deterministic safety checks.

Qwen3 only PROPOSES values. Python then (1) normalises them and (2) "grounds" them:
a value is kept only if it can be found in the customer's actual message. This stops the
model from inventing requirements. Nothing here is pure-LLM trust; no defaults are applied.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from app.constants import ALLOWED, REQUIREMENT_FIELDS
from config.logging_config import get_logger

log = get_logger(__name__)

INTENTS = ("new_quotation", "modify_quotation", "retrieve_quotation", "general_question")

MATERIAL_SYNONYMS = {"wood": "wood", "wooden": "wood", "plastic": "plastic",
                     "metal": "metal", "metallic": "metal"}
GLASS_SYNONYMS = {"standard": "standard", "standard glass": "standard",
                  "acrylic": "acrylic", "acrylic glass": "acrylic"}

_SIZE_RE = re.compile(r"(\d{1,2})\s*(?:x|×|\*|by)\s*(\d{1,2})", re.I)
_MATERIAL_RE = re.compile(r"\b(wood|wooden|plastic|metal|metallic)\b", re.I)
_GLASS_RE = re.compile(r"\b(acrylic|standard)\b", re.I)

PROMPT = """
You extract photo-frame requirements from a customer message. Reply with ONE JSON object only.

Keys:
  "intent": one of "new_quotation", "modify_quotation", "retrieve_quotation", "general_question"
  "frame_size": size the customer stated, e.g. "4x6", or null
  "frame_material": material the customer stated, or null
  "glass_type": glass type the customer stated, or null

Rules:
- Use null for anything the customer did not clearly state. NEVER guess or default.
- Copy values as the customer said them. Do not correct or substitute them.
- Do not invent prices or quotation numbers.
{context}
Customer message: {message}
JSON:"""


@dataclass
class ExtractionResult:
    intent: str = "general_question"
    fields: dict[str, Optional[str]] = field(default_factory=lambda: {f: None for f in REQUIREMENT_FIELDS})
    dropped: list[str] = field(default_factory=list)   # fields rejected by the grounding check


# ---------- normalisation ----------
def normalize_size(raw: str) -> str:
    s = raw.lower().replace("×", "x").replace("*", "x")
    s = re.sub(r"\b(inches|inch|in)\b|\"", "", s)
    s = s.replace(" by ", "x")
    return re.sub(r"\s+", "", s)


def normalize_value(field_name: str, raw: str) -> str:
    raw = raw.strip().lower()
    if field_name == "frame_size":
        return normalize_size(raw)
    table = MATERIAL_SYNONYMS if field_name == "frame_material" else GLASS_SYNONYMS
    return table.get(raw, raw)


def _found_in_text(field_name: str, text: str) -> set[str]:
    """Allowed canonical values that the customer's text deterministically mentions."""
    if field_name == "frame_size":
        return {f"{a}x{b}" for a, b in _SIZE_RE.findall(text)}
    if field_name == "frame_material":
        return {MATERIAL_SYNONYMS[m.lower()] for m in _MATERIAL_RE.findall(text)}
    return {m.lower() for m in _GLASS_RE.findall(text)}


def is_grounded(field_name: str, value: str, text: str) -> bool:
    """True only if `value` is clearly supported by the message and unambiguous."""
    if value in ALLOWED[field_name]:
        return _found_in_text(field_name, text) == {value}   # exactly one, and it matches
    # Not an allowed value: keep it (so we can report it as invalid) only if the customer
    # literally wrote it.
    squashed = re.sub(r"\s+", "", normalize_size(text) if field_name == "frame_size" else text.lower())
    return value.replace(" ", "") in squashed


# ---------- LLM output parsing ----------
def parse_llm_json(content: str) -> dict[str, Any]:
    content = re.sub(r"<think>.*?</think>", "", content or "", flags=re.S)
    match = re.search(r"\{.*\}", content, flags=re.S)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def extract_from_message(llm, message: str, collected: dict[str, Optional[str]],
                         asked_fields: list[str]) -> ExtractionResult:
    """Run qwen on one customer message and return grounded, normalised values."""
    context = ""
    if asked_fields:
        context = ("The assistant just asked the customer about: "
                   + ", ".join(asked_fields) + ". The message is probably the answer.\n")
    try:
        content = llm.invoke(PROMPT.format(context=context, message=message)).content
    except Exception:  # LLM down / timeout: degrade to "nothing extracted"
        log.exception("llm_extraction_failed")
        return ExtractionResult()

    data = parse_llm_json(content)
    if not data:
        log.warning("llm_output_unparseable", content=str(content)[:200])

    result = ExtractionResult(intent=data.get("intent") if data.get("intent") in INTENTS else "general_question")
    for f in REQUIREMENT_FIELDS:
        raw = data.get(f)
        if not isinstance(raw, str) or not raw.strip():
            continue
        value = normalize_value(f, raw)
        if is_grounded(f, value, message):
            result.fields[f] = value
        else:
            result.dropped.append(f)
            log.warning("extraction_not_grounded", field=f, value=value)
    log.info("extraction_done", intent=result.intent, fields=result.fields, dropped=result.dropped)
    return result
