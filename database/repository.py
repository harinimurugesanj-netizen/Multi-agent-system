"""
 * every query is a fixed, parameterized statement (the LLM never writes SQL);
 * every query touching quotations/threads is scoped by customer_id (authorization);
 * functions take an open Connection so callers control the transaction.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Connection, text

from app.constants import PROFIT_MARGIN, WASTAGE_RATE
from app.errors import PersistenceError, PricingNotFound, QuotationNotFound, UnauthorizedAccess
from config.logging_config import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------- prices
_FRAME_PRICE = text("SELECT price FROM frame_prices WHERE frame_size = :size AND frame_material = :material")
_GLASS_PRICE = text("SELECT price FROM glass_prices WHERE frame_size = :size AND glass_type = :glass")
_LABOUR = text("SELECT labour_cost FROM labour_prices WHERE frame_size = :size")


@dataclass(frozen=True)
class PriceBundle:
    material_price: Decimal
    glass_price: Decimal
    labour_cost: Decimal


def fetch_prices(conn: Connection, size: str, material: str, glass: str) -> PriceBundle:
    """Fetch all three prices. Raises PricingNotFound listing EVERY missing item; never guesses."""
    frame = conn.execute(_FRAME_PRICE, {"size": size, "material": material}).scalar_one_or_none()
    glass_p = conn.execute(_GLASS_PRICE, {"size": size, "glass": glass}).scalar_one_or_none()
    labour = conn.execute(_LABOUR, {"size": size}).scalar_one_or_none()

    missing = [name for name, val in (
        (f"frame price ({size}, {material})", frame),
        (f"glass price ({size}, {glass})", glass_p),
        (f"labour cost ({size})", labour)) if val is None]
    if missing:
        log.error("pricing_missing", missing=missing)
        raise PricingNotFound("; ".join(missing), missing=missing)
    return PriceBundle(Decimal(frame), Decimal(glass_p), Decimal(labour))


def list_options(conn: Connection) -> dict[str, list[str]]:
    """Options actually priced in the database (used for general questions)."""
    sizes = conn.execute(text("SELECT frame_size FROM labour_prices ORDER BY frame_size")).scalars().all()
    materials = conn.execute(text("SELECT DISTINCT frame_material FROM frame_prices ORDER BY 1")).scalars().all()
    glass = conn.execute(text("SELECT DISTINCT glass_type FROM glass_prices ORDER BY 1")).scalars().all()
    return {"frame_size": list(sizes), "frame_material": list(materials), "glass_type": list(glass)}


# ---------------------------------------------------------------- customers & threads
def get_customer_id(conn: Connection, external_id: str) -> int:
    """Map the authenticated user's external id to customers.id."""
    cid = conn.execute(text("SELECT id FROM customers WHERE external_id = :e"),
                       {"e": external_id}).scalar_one_or_none()
    if cid is None:
        log.warning("unknown_customer", external_id=external_id)
        raise UnauthorizedAccess("unknown customer")
    return int(cid)


def claim_or_verify_thread(conn: Connection, thread_id: str, customer_id: int) -> None:
    """First use claims the thread for this customer; later use must match the owner."""
    conn.execute(text("INSERT INTO conversation_threads (thread_id, customer_id) "
                      "VALUES (:t, :c) ON CONFLICT (thread_id) DO NOTHING"),
                 {"t": thread_id, "c": customer_id})
    owner = conn.execute(text("SELECT customer_id FROM conversation_threads WHERE thread_id = :t"),
                         {"t": thread_id}).scalar_one()
    if int(owner) != customer_id:
        log.warning("thread_access_denied", thread_id=thread_id, customer_id=customer_id)
        raise UnauthorizedAccess("thread belongs to another customer")


# ---------------------------------------------------------------- quotations
@dataclass(frozen=True)
class QuotationRecord:
    id: str
    customer_id: int
    thread_id: str
    original_quotation_id: Optional[str]
    revision_number: int
    frame_size: str
    frame_material: str
    glass_type: str
    material_price: Decimal
    glass_price: Decimal
    labour_cost: Decimal
    wastage_cost: Decimal
    total_production_cost: Decimal
    profit_margin: Decimal
    selling_price: Decimal
    created_at: datetime


_Q_COLS = ("id::text AS id, customer_id, thread_id, original_quotation_id::text AS original_quotation_id, "
           "revision_number, frame_size, frame_material, glass_type, material_price, glass_price, "
           "labour_cost, wastage_cost, total_production_cost, profit_margin, selling_price, created_at")

_GET_Q = text(f"SELECT {_Q_COLS} FROM quotations "
              "WHERE id = CAST(:id AS uuid) AND customer_id = :cid AND status = 'completed'")

_FIND_Q = text(f"SELECT {_Q_COLS} FROM quotations "
               "WHERE customer_id = :cid AND status = 'completed' "
               "AND (CAST(:size AS text) IS NULL OR frame_size = :size) "
               "AND (CAST(:material AS text) IS NULL OR frame_material = :material) "
               "AND (CAST(:glass AS text) IS NULL OR glass_type = :glass) "
               "ORDER BY created_at DESC LIMIT :lim")


def get_quotation(conn: Connection, customer_id: int, quotation_id: str) -> QuotationRecord:
    """Owned quotations only. Someone else's id looks identical to a non-existent one."""
    try:
        row = conn.execute(_GET_Q, {"id": quotation_id, "cid": customer_id}).mappings().first()
    except Exception as exc:  # malformed uuid etc. surfaces as DB error; treat as not found
        if "uuid" in str(exc).lower():
            raise QuotationNotFound(f"invalid id {quotation_id!r}") from exc
        raise
    if row is None:
        log.warning("quotation_not_found", customer_id=customer_id, quotation_id=quotation_id)
        raise QuotationNotFound(quotation_id)
    return QuotationRecord(**row)


def find_quotations(conn: Connection, customer_id: int, *, size: str | None = None,
                    material: str | None = None, glass: str | None = None,
                    limit: int = 5) -> list[QuotationRecord]:
    """Newest first. Filters are optional; an empty result is returned, not raised."""
    rows = conn.execute(_FIND_Q, {"cid": customer_id, "size": size, "material": material,
                                  "glass": glass, "lim": limit}).mappings().all()
    return [QuotationRecord(**r) for r in rows]


@dataclass(frozen=True)
class NewQuotation:
    customer_id: int
    thread_id: str
    frame_size: str
    frame_material: str
    glass_type: str
    material_price: Decimal
    glass_price: Decimal
    labour_cost: Decimal
    wastage_cost: Decimal
    total_production_cost: Decimal
    selling_price: Decimal
    idempotency_key: str                      # e.g. f"{thread_id}:{run_id}"
    original_quotation_id: Optional[str] = None


_INSERT_Q = text(
    "INSERT INTO quotations (customer_id, thread_id, original_quotation_id, revision_number, "
    "frame_size, frame_material, glass_type, material_price, glass_price, labour_cost, "
    "wastage_rate, wastage_cost, total_production_cost, profit_margin, selling_price, "
    "status, idempotency_key) VALUES (:cid, :tid, CAST(:orig AS uuid), :rev, :size, :material, "
    ":glass, :mp, :gp, :lc, :wr, :wc, :tpc, :pm, :sp, 'completed', :key) "
    "ON CONFLICT (idempotency_key) DO NOTHING RETURNING id::text")


def save_quotation(conn: Connection, q: NewQuotation) -> str:
    """Insert a NEW quotation row (never updates an existing one). Idempotent per key.

    A revision links to the quotation it was derived from, which must belong to the same
    customer. Call inside db_transaction() so the insert commits only if everything succeeds.
    """
    revision = 0
    if q.original_quotation_id:
        parent = get_quotation(conn, q.customer_id, q.original_quotation_id)   # ownership check
        revision = parent.revision_number + 1

    new_id = conn.execute(_INSERT_Q, {
        "cid": q.customer_id, "tid": q.thread_id, "orig": q.original_quotation_id, "rev": revision,
        "size": q.frame_size, "material": q.frame_material, "glass": q.glass_type,
        "mp": q.material_price, "gp": q.glass_price, "lc": q.labour_cost,
        "wr": WASTAGE_RATE, "wc": q.wastage_cost, "tpc": q.total_production_cost,
        "pm": PROFIT_MARGIN, "sp": q.selling_price, "key": q.idempotency_key,
    }).scalar_one_or_none()

    if new_id is None:   # same key already saved: a retry. Return the existing row (same customer only).
        new_id = conn.execute(
            text("SELECT id::text FROM quotations WHERE idempotency_key = :k AND customer_id = :c"),
            {"k": q.idempotency_key, "c": q.customer_id}).scalar_one_or_none()
        if new_id is None:
            raise PersistenceError("idempotency key conflict")
        log.info("quotation_save_deduplicated", quotation_id=new_id)
    else:
        log.info("quotation_saved", quotation_id=new_id, customer_id=q.customer_id,
                 original_quotation_id=q.original_quotation_id, revision=revision)
    return new_id
