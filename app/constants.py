"""Single source of truth for allowed values, rates and the rounding policy."""
from decimal import Decimal, ROUND_HALF_UP

VALID_SIZES: tuple[str, ...] = ("4x6", "5x7", "6x8", "8x10")
VALID_MATERIALS: tuple[str, ...] = ("wood", "plastic", "metal")
VALID_GLASS: tuple[str, ...] = ("standard", "acrylic")

REQUIREMENT_FIELDS: tuple[str, ...] = ("frame_size", "frame_material", "glass_type")
ALLOWED: dict[str, tuple[str, ...]] = {
    "frame_size": VALID_SIZES,
    "frame_material": VALID_MATERIALS,
    "glass_type": VALID_GLASS,
}

MAX_REPAIRS = 2                          # LLM repair passes per customer message
WASTAGE_RATE = Decimal("0.05")
PROFIT_MARGIN = Decimal("0.10")          # share of the SELLING price
MONEY_QUANT = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    """Policy: Decimal arithmetic, round half-up to 2 dp, applied to each stored value."""
    return value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)