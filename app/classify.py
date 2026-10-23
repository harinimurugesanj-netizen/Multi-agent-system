from dataclasses import dataclass, field

from app.constants import REQUIREMENT_FIELDS
from app.errors import LLMUnavailable
from app.extraction import INTENTS, is_grounded, normalize_value, parse_llm_json
from config.logging_config import get_logger

log = get_logger(__name__)

PROMPT = """You are the intent router for a photo-frame shop assistant. Reply with ONE JSON object only.

"intent" is exactly one of:
  "new_quotation"      customer wants a price/estimate for a new frame
  "modify_quotation"   customer wants to change something in a PREVIOUS quotation
  "retrieve_quotation" customer asks what a previous quotation was, or asks for their quotation history
  "general_question"   anything else (what sizes/materials/glass do you have, greetings, ...)
"requested": what the customer WANTS, with keys "frame_size", "frame_material", "glass_type" (null if not stated).
"reference": only attributes that IDENTIFY which previous quotation they mean (e.g. "my 5x7 wooden one"), same three keys, null if not stated.

Rules: use null unless clearly stated. Never guess or default. Copy values as the customer wrote them.

Examples:
"I need a 4x6 wooden frame" -> {"intent":"new_quotation","requested":{"frame_size":"4x6","frame_material":"wood","glass_type":null},"reference":{"frame_size":null,"frame_material":null,"glass_type":null}}
"In my previous quotation, change only the glass to standard" -> {"intent":"modify_quotation","requested":{"frame_size":null,"frame_material":null,"glass_type":"standard"},"reference":{"frame_size":null,"frame_material":null,"glass_type":null}}
"What was my 5x7 quotation?" -> {"intent":"retrieve_quotation","requested":{"frame_size":null,"frame_material":null,"glass_type":null},"reference":{"frame_size":"5x7","frame_material":null,"glass_type":null}}
"What materials do you have?" -> {"intent":"general_question","requested":{"frame_size":null,"frame_material":null,"glass_type":null},"reference":{"frame_size":null,"frame_material":null,"glass_type":null}}

Customer message: {message}
JSON:"""


@dataclass
class Classification:
    intent: str = "general_question"
    requested: dict[str, str] = field(default_factory=dict)
    reference: dict[str, str] = field(default_factory=dict)
    dropped: list[str] = field(default_factory=list)


def _clean(data, text: str, label: str, dropped: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    if not isinstance(data, dict):
        return out
    for f in REQUIREMENT_FIELDS:
        raw = data.get(f)
        if not isinstance(raw, str) or not raw.strip():
            continue
        value = normalize_value(f, raw)
        if is_grounded(f, value, text):
            out[f] = value
        else:
            dropped.append(f"{label}.{f}")
            log.warning("classification_not_grounded", field=f, label=label, value=value)
    return out


def classify_message(llm, message: str) -> Classification:
    """Raises LLMUnavailable if the model cannot be reached."""
    try:
        content = llm.invoke(PROMPT.replace("{message}", message)).content
    except Exception as exc:
        log.exception("llm_classification_failed")
        raise LLMUnavailable(str(exc)[:200]) from exc
    data = parse_llm_json(content)
    result = Classification()
    if not data:
        log.warning("classification_unparseable", content=str(content)[:200])
        return result
    if data.get("intent") in INTENTS:
        result.intent = data["intent"]
    result.requested = _clean(data.get("requested"), message, "requested", result.dropped)
    result.reference = _clean(data.get("reference"), message, "reference", result.dropped)
    log.info("classified", intent=result.intent, requested=result.requested,
             reference=result.reference, dropped=result.dropped)
    return result
