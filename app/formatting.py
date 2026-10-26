"""Customer-facing text helpers and the numeric check applied to LLM-written replies."""
import re
from datetime import datetime
from decimal import Decimal

_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def fmt_money(value, currency: str = "") -> str:
    return f"{currency}{Decimal(str(value)):,.2f}"


def short_ref(quotation_id: str) -> str:
    return quotation_id.replace("-", "")[:8].upper()


def describe_items(size: str, material: str, glass: str) -> str:
    glass_name = "acrylic glass" if glass == "acrylic" else "standard glass"
    return f"{size.replace('x', '×')} inch {material} frame with {glass_name}"


def quotation_text(c: dict, currency: str = "") -> str:
    day = datetime.fromisoformat(c["created_at"]).strftime("%d %b %Y")
    text = (f"Quotation {short_ref(c['id'])} ({day}): "
            f"{describe_items(c['frame_size'], c['frame_material'], c['glass_type'])}. "
            f"Total: {fmt_money(c['selling_price'], currency)}.")
    if c.get("original_quotation_id"):
        text += " This is a revision of an earlier quotation."
    return text


def fallback_response(size, material, glass, selling_price, currency="", is_revision=False) -> str:
    head = "Here is your revised quotation (your original quotation is unchanged)." if is_revision \
        else "Here is your quotation."
    return (f"{head}\nItem: {describe_items(size, material, glass)}\n"
            f"Total: {fmt_money(selling_price, currency)}")


def verify_response(text: str, selling_price, size: str) -> bool:
    """True only if the text states the correct total and no other numbers.

    Allowed numbers: the selling price and the two size numbers. Anything else means the
    LLM invented or altered a figure, so the caller falls back to a fixed template.
    """
    price = f"{Decimal(str(selling_price)):.2f}"
    allowed = {price, price.rstrip("0").rstrip("."), *size.split("x")}
    tokens = {t.replace(",", "") for t in _NUM.findall(text)}
    return price in tokens and tokens <= allowed
