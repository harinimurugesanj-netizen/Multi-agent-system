"""Clarification questions. Options come from the DATABASE catalog; the text is built by Python
so nothing can be invented."""
from typing import Mapping

from app.options import join_options


def build_question(missing_fields: list[str], invalid_fields: dict[str, str], problems: list[str],
                   catalog: Mapping) -> str:
    asks = {
        "frame_size": f"Which frame size would you like ({join_options('frame_size', catalog.get('frame_size', []))} inches)?",
        "frame_material": f"Which frame material would you prefer: {join_options('frame_material', catalog.get('frame_material', []))}?",
        "glass_type": f"Which glass type would you prefer: {join_options('glass_type', catalog.get('glass_type', []))}?",
    }
    ask_list = [asks[f] for f in missing_fields]
    if len(ask_list) == 1 and not problems:
        return ask_list[0]
    parts = list(problems)
    if ask_list:
        parts.append("To prepare your quotation I still need: " + " ".join(ask_list))
    elif invalid_fields:
        parts.append("Please tell me which one you would like.")
    return " ".join(parts)