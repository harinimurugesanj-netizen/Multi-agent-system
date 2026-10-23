"""Stage 4: deterministic estimation. No LLM involvement.

Rounding policy (applied consistently): Decimal arithmetic; wastage_cost and selling_price
are rounded half-up to 2 dp; total_production_cost is the exact sum of 2-dp values.
  wastage_cost          = (material + glass) * 5%
  total_production_cost = material + glass + wastage + labour
  selling_price         = total_production_cost / 0.90      (profit = 10% of selling price)
"""
from dataclasses import dataclass, fields
from decimal import Decimal

from app.constants import PROFIT_MARGIN, WASTAGE_RATE, money


@dataclass(frozen=True)
class Estimation:
    material_price: Decimal
    glass_price: Decimal
    labour_cost: Decimal
    wastage_cost: Decimal
    total_production_cost: Decimal
    profit_margin: Decimal
    selling_price: Decimal


def calculate_estimation(material_price: Decimal, glass_price: Decimal, labour_cost: Decimal) -> Estimation:
    wastage = money((material_price + glass_price) * WASTAGE_RATE)
    total = money(material_price + glass_price + wastage + labour_cost)
    selling = money(total / (Decimal("1") - PROFIT_MARGIN))
    return Estimation(material_price, glass_price, labour_cost, wastage, total, PROFIT_MARGIN, selling)


def validate_estimation(est: Estimation) -> list[str]:
    """Return a list of problems (empty list = safe to save). Recomputes independently."""
    problems: list[str] = []
    for f in fields(est):
        v = getattr(est, f.name)
        if not isinstance(v, Decimal) or not v.is_finite():
            problems.append(f"{f.name} is not a finite Decimal")
        elif v < 0:
            problems.append(f"{f.name} is negative")
    if problems:
        return problems
    if est.material_price <= 0 or est.glass_price <= 0:
        problems.append("material/glass price is zero (price list incomplete?)")
    if est.selling_price <= 0:
        problems.append("selling price is not positive")
    expected = calculate_estimation(est.material_price, est.glass_price, est.labour_cost)
    for f in fields(est):
        if getattr(est, f.name) != getattr(expected, f.name):
            problems.append(f"{f.name} differs from recomputed value")
    if est.selling_price < est.total_production_cost:
        problems.append("selling price below production cost")
    if abs((est.selling_price - est.total_production_cost) - est.selling_price * PROFIT_MARGIN) > Decimal("0.01"):
        problems.append("profit is not 10% of selling price")
    return problems
