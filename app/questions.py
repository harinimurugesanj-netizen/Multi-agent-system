"""Stage 2b: deterministic clarification questions (no LLM, so nothing can be invented)."""
from app.constants import VALID_GLASS, VALID_MATERIALS, VALID_SIZES

_LABEL = {"frame_size": "frame size", "frame_material": "frame material", "glass_type": "glass type"}
_OPTIONS = {
    "frame_size": ", ".join(s.replace("x", "×") for s in VALID_SIZES) + " inches",
    "frame_material": ", ".join(VALID_MATERIALS),
    "glass_type": "standard glass or acrylic",
}
_ASK = {
    "frame_size": "Which frame size would you like ({o})?",
    "frame_material": "Which frame material would you prefer: wood, plastic or metal?",
    "glass_type": "Which glass type would you prefer: standard glass or acrylic?",
}


def build_question(missing_fields: list[str], invalid_fields: dict[str, str]) -> str:
    parts: list[str] = []
    for f, raw in invalid_fields.items():
        parts.append(f'"{raw}" is not an available {_LABEL[f]}. Available options: {_OPTIONS[f]}.')
    asks = [_ASK[f].format(o=_OPTIONS[f]) for f in missing_fields]
    if len(asks) == 1 and not parts:
        return asks[0]
    if asks:
        parts.append("To prepare your quotation I still need: " + " ".join(asks))
    return " ".join(parts)
