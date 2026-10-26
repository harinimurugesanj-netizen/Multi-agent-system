"""LLM-first extraction. Qwen understands typos, synonyms and any wording; Python only checks:
  1. the model quoted EVIDENCE (exact words) for every value it returns, and those words really
     appear in the customer's message (so it cannot invent a value from nothing);
  2. later, the database catalog decides whether the value is actually offered (requirements.py).
No synonym tables, no spelling rules.
"""
import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from app.constants import REQUIREMENT_FIELDS
from config.logging_config import get_logger
from app.options import options_text

log = get_logger(__name__)

INTENTS = ("new_quotation", "modify_quotation", "retrieve_quotation", "general_question")

FORMAT_HELP = """Each field is null, or an object {"value": <one of our options>, "evidence": <the exact words copied from the customer's message that name it>}."""

RULES = """Rules:
- Understand typos, synonyms and any wording, and answer with the matching option from our list (for example "woden" -> wood, "4 into 6" -> 4x6).
- If the customer asks for something that is NOT in our options and is not another way of writing one, put it in "value" exactly as written, so we can tell them it is unavailable.
- Use only what the customer actually said. If a field is not mentioned, use null. Never guess and never use defaults.
- "evidence" must be copied exactly (same letters) from the customer's message."""

EXTRACT_PROMPT = """
You extract photo-frame requirements from a customer's message. Reply with ONE JSON object only.

Our current options (from the database):
{options}

Return {"frame_size": F, "frame_material": F, "glass_type": F}. """ + FORMAT_HELP + """
""" + RULES + """
{context}
Customer message: {message}
JSON:"""

REPAIR_PROMPT = """
You extracted photo-frame requirements from a customer's message, but checking them against our database found problems. Fix your JSON. Reply with ONE JSON object only.

Our current options (from the database):
{options}

Customer message: {message}
Your previous JSON: {previous}
Problems found:
{problems}

Return {"frame_size": F, "frame_material": F, "glass_type": F}. """ + FORMAT_HELP + """
""" + RULES + """
- If a problem is that a field is missing and the customer really did not mention it, keep it null.
JSON:"""


@dataclass
class ExtractionResult:
    fields: dict[str, Optional[str]] = field(default_factory=dict)
    dropped: list[str] = field(default_factory=list)      # fields rejected by the evidence check


def _norm(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower()).strip()


def evidence_ok(evidence: Any, message: str) -> bool:
    ev = _norm(evidence) if isinstance(evidence, str) else ""
    return len(ev) >= 2 and ev in _norm(message)


def clean_value(field_name: str, value: str) -> str:
    v = value.strip().lower()
    if field_name == "frame_size":      # only trivial formatting, no word lists
        v = re.sub(r"\s+|inches$|inch$|in$|\"$", "", v.replace("×", "x").replace("*", "x"))
    return v


def read_fields(group: Any, message: str, label: str) -> tuple[dict[str, str], list[str]]:
    """Pick {value, evidence} items out of an LLM object; keep only evidence-backed values."""
    out: dict[str, str] = {}
    dropped: list[str] = []
    if not isinstance(group, dict):
        return out, dropped
    for f in REQUIREMENT_FIELDS:
        item = group.get(f)
        if not isinstance(item, dict) or not isinstance(item.get("value"), str) or not item["value"].strip():
            continue
        if evidence_ok(item.get("evidence"), message):
            out[f] = clean_value(f, item["value"])
        else:
            dropped.append(f"{label}.{f}")
            log.warning("evidence_check_failed", field=f, label=label, value=item["value"])
    return out, dropped


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


def _run(llm, prompt: str, message: str, label: str) -> ExtractionResult:
    try:
        content = llm.invoke(prompt).content
    except Exception:
        log.exception("llm_call_failed", label=label)
        return ExtractionResult()
    data = parse_llm_json(content)
    if content and not data:
        log.warning("llm_output_unparseable", label=label, content=str(content)[:200])
    fields, dropped = read_fields(data, message, label)
    log.info("llm_fields_read", label=label, fields=fields, dropped=dropped)
    return ExtractionResult(fields=fields, dropped=dropped)


def extract_from_message(llm, message: str, catalog: Mapping, asked_fields: list[str]) -> ExtractionResult:
    """Extract requirements from one customer message (e.g. the answer to a question)."""
    context = ""
    if asked_fields:
        context = ("The assistant just asked the customer about: " + ", ".join(asked_fields)
                   + ". The message is probably the answer.\n")
    prompt = (EXTRACT_PROMPT.replace("{options}", options_text(catalog))
              .replace("{context}", context).replace("{message}", message))
    return _run(llm, prompt, message, "extract")


def repair_from_message(llm, message: str, current: Mapping[str, Any], problems: list[str],
                        catalog: Mapping) -> ExtractionResult:
    """Send the database's validation problems back to the model and let it fix its JSON."""
    prompt = (REPAIR_PROMPT.replace("{options}", options_text(catalog)).replace("{message}", message)
              .replace("{previous}", json.dumps({f: current.get(f) for f in REQUIREMENT_FIELDS}))
              .replace("{problems}", "\n".join(f"- {p}" for p in problems) or "- (none listed)"))
    return _run(llm, prompt, message, "repair")