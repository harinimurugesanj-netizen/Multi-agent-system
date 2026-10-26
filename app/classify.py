"""One Qwen3 call: intent + requested values + which old quotation is meant (all evidence-checked)."""
from dataclasses import dataclass, field
from typing import Mapping

from app.errors import LLMUnavailable
from app.extraction import FORMAT_HELP, INTENTS, RULES, evidence_ok, parse_llm_json, read_fields
from config.logging_config import get_logger
from app.options import options_text

log = get_logger(__name__)

PROMPT = """
You are the intent router for a photo-frame shop assistant. Reply with ONE JSON object only.

Our current options (from the database):
{options}

Return {"intent": I, "reference_latest": R, "requested": G, "reference": G}

"intent" is exactly one of:
  "new_quotation"      customer wants a price/estimate for a new frame
  "modify_quotation"   customer wants to change something in a PREVIOUS quotation
  "retrieve_quotation" customer asks what a previous quotation was, or asks for their quotation history
  "general_question"   anything else (what options do you have, greetings, ...)
G is an object {"frame_size": F, "frame_material": F, "glass_type": F}. """ + FORMAT_HELP + """
"requested" = what the customer WANTS for the frame. "reference" = attributes that only IDENTIFY which previous quotation they mean (for example "my 5x7 wooden one").
"reference_latest" = null, or the exact words from the message by which the customer points at their most recent quotation (for example "my previous quotation").
""" + RULES + """

Examples:
"i want a 4 into 6 woden frame with acrilic glass" -> {"intent":"new_quotation","reference_latest":null,"requested":{"frame_size":{"value":"4x6","evidence":"4 into 6"},"frame_material":{"value":"wood","evidence":"woden"},"glass_type":{"value":"acrylic","evidence":"acrilic"}},"reference":{"frame_size":null,"frame_material":null,"glass_type":null}}
"In my previous quotation, change only the glass to standard" -> {"intent":"modify_quotation","reference_latest":"my previous quotation","requested":{"frame_size":null,"frame_material":null,"glass_type":{"value":"standard","evidence":"standard"}},"reference":{"frame_size":null,"frame_material":null,"glass_type":null}}
"What was my 5x7 quotation?" -> {"intent":"retrieve_quotation","reference_latest":null,"requested":{"frame_size":null,"frame_material":null,"glass_type":null},"reference":{"frame_size":{"value":"5x7","evidence":"5x7"},"frame_material":null,"glass_type":null}}
"What materials do you have?" -> {"intent":"general_question","reference_latest":null,"requested":{"frame_size":null,"frame_material":null,"glass_type":null},"reference":{"frame_size":null,"frame_material":null,"glass_type":null}}

Customer message: {message}
JSON:"""


@dataclass
class Classification:
    intent: str = "general_question"
    requested: dict[str, str] = field(default_factory=dict)
    reference: dict[str, str] = field(default_factory=dict)
    reference_latest: bool = False
    dropped: list[str] = field(default_factory=list)


def classify_message(llm, message: str, catalog: Mapping) -> Classification:
    """Raises LLMUnavailable if the model cannot be reached."""
    prompt = PROMPT.replace("{options}", options_text(catalog)).replace("{message}", message)
    try:
        content = llm.invoke(prompt).content
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
    result.requested, d1 = read_fields(data.get("requested"), message, "requested")
    result.reference, d2 = read_fields(data.get("reference"), message, "reference")
    result.reference_latest = evidence_ok(data.get("reference_latest"), message)
    result.dropped = d1 + d2
    log.info("classified", intent=result.intent, requested=result.requested, reference=result.reference,
             latest=result.reference_latest, dropped=result.dropped)
    return result