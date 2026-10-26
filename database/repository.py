"""
 * every query is built from SQLAlchemy ORM models and is parameterized (the LLM never writes SQL);
 * every query touching quotations/threads is scoped by customer_id (authorization);
 * functions take an open Connection so callers control the transaction.

The public API (function names, signatures, dataclasses) is identical to the raw-SQL version,
so nodes.py, service.py and the tests do not change. The models below only MAP existing tables;
schema.sql stays the source of truth for DDL, constraints and the immutability trigger
(do not call Base.metadata.create_all()).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, Connection, DateTime, Integer, Numeric, Text, select
from sqlalchemy.dialects.postgresql import UUID, insert as pg_insert
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.constants import PROFIT_MARGIN, WASTAGE_RATE
from app.errors import PersistenceError, PricingNotFound, QuotationNotFound, UnauthorizedAccess
from config.logging_config import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------- models (mapping only)
class Base(DeclarativeBase):
    pass


class FramePrice(Base):
    __tablename__ = "frame_prices"
    frame_size: Mapped[str] = mapped_column(Text, primary_key=True)
    frame_material: Mapped[str] = mapped_column(Text, primary_key=True)
    price: Mapped[Decimal] = mapped_column(Numeric)


class GlassPrice(Base):
    __tablename__ = "glass_prices"
    frame_size: Mapped[str] = mapped_column(Text, primary_key=True)
    glass_type: Mapped[str] = mapped_column(Text, primary_key=True)
    price: Mapped[Decimal] = mapped_column(Numeric)


class LabourPrice(Base):
    __tablename__ = "labour_prices"
    frame_size: Mapped[str] = mapped_column(Text, primary_key=True)
    labour_cost: Mapped[Decimal] = mapped_column(Numeric)


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    external_id: Mapped[str] = mapped_column(Text)
    name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    email: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ConversationThread(Base):
    __tablename__ = "conversation_threads"
    thread_id: Mapped[str] = mapped_column(Text, primary_key=True)
    customer_id: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Quotation(Base):
    __tablename__ = "quotations"
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    customer_id: Mapped[int] = mapped_column(BigInteger)
    thread_id: Mapped[str] = mapped_column(Text)
    original_quotation_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), nullable=True)
    revision_number: Mapped[int] = mapped_column(Integer)
    frame_size: Mapped[str] = mapped_column(Text)
    frame_material: Mapped[str] = mapped_column(Text)
    glass_type: Mapped[str] = mapped_column(Text)
    material_price: Mapped[Decimal] = mapped_column(Numeric)
    glass_price: Mapped[Decimal] = mapped_column(Numeric)
    labour_cost: Mapped[Decimal] = mapped_column(Numeric)
    wastage_rate: Mapped[Decimal] = mapped_column(Numeric)
    wastage_cost: Mapped[Decimal] = mapped_column(Numeric)
    total_production_cost: Mapped[Decimal] = mapped_column(Numeric)
    profit_margin: Mapped[Decimal] = mapped_column(Numeric)
    selling_price: Mapped[Decimal] = mapped_column(Numeric)
    status: Mapped[str] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------- prices
@dataclass(frozen=True)
class PriceBundle:
    material_price: Decimal
    glass_price: Decimal
    labour_cost: Decimal


def fetch_prices(conn: Connection, size: str, material: str, glass: str) -> PriceBundle:
    """Fetch all three prices. Raises PricingNotFound listing EVERY missing item; never guesses."""
    frame = conn.execute(select(FramePrice.price).where(
        FramePrice.frame_size == size, FramePrice.frame_material == material)).scalar_one_or_none()
    glass_p = conn.execute(select(GlassPrice.price).where(
        GlassPrice.frame_size == size, GlassPrice.glass_type == glass)).scalar_one_or_none()
    labour = conn.execute(select(LabourPrice.labour_cost).where(
        LabourPrice.frame_size == size)).scalar_one_or_none()

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
    sizes = conn.execute(select(LabourPrice.frame_size).order_by(LabourPrice.frame_size)).scalars().all()
    materials = conn.execute(select(FramePrice.frame_material).distinct()
                             .order_by(FramePrice.frame_material)).scalars().all()
    glass = conn.execute(select(GlassPrice.glass_type).distinct()
                         .order_by(GlassPrice.glass_type)).scalars().all()
    return {"frame_size": list(sizes), "frame_material": list(materials), "glass_type": list(glass)}


def get_catalog(conn: Connection) -> dict:
    """Everything the database currently offers, incl. which size+material / size+glass pairs
    actually have a price row. The single source of truth for validation and for LLM prompts."""
    frame = [[r[0], r[1]] for r in conn.execute(
        select(FramePrice.frame_size, FramePrice.frame_material)).all()]
    glass = [[r[0], r[1]] for r in conn.execute(
        select(GlassPrice.frame_size, GlassPrice.glass_type)).all()]
    labour = list(conn.execute(select(LabourPrice.frame_size)).scalars().all())
    sizes = sorted(set(labour) & {s for s, _ in frame} & {s for s, _ in glass})
    return {"frame_size": sizes,
            "frame_material": sorted({m for s, m in frame if s in sizes}),
            "glass_type": sorted({g for s, g in glass if s in sizes}),
            "frame_combos": [c for c in frame if c[0] in sizes],
            "glass_combos": [c for c in glass if c[0] in sizes]}


# ---------------------------------------------------------------- customers & threads
def get_customer_id(conn: Connection, external_id: str) -> int:
    """Map the authenticated user's external id to customers.id."""
    cid = conn.execute(select(Customer.id).where(Customer.external_id == external_id)).scalar_one_or_none()
    if cid is None:
        log.warning("unknown_customer", external_id=external_id)
        raise UnauthorizedAccess("unknown customer")
    return int(cid)


def claim_or_verify_thread(conn: Connection, thread_id: str, customer_id: int) -> None:
    """First use claims the thread for this customer; later use must match the owner."""
    conn.execute(pg_insert(ConversationThread)
                 .values(thread_id=thread_id, customer_id=customer_id)
                 .on_conflict_do_nothing(index_elements=[ConversationThread.thread_id]))
    owner = conn.execute(select(ConversationThread.customer_id)
                         .where(ConversationThread.thread_id == thread_id)).scalar_one()
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


_Q_COLS = (Quotation.id, Quotation.customer_id, Quotation.thread_id, Quotation.original_quotation_id,
           Quotation.revision_number, Quotation.frame_size, Quotation.frame_material,
           Quotation.glass_type, Quotation.material_price, Quotation.glass_price,
           Quotation.labour_cost, Quotation.wastage_cost, Quotation.total_production_cost,
           Quotation.profit_margin, Quotation.selling_price, Quotation.created_at)


def get_quotation(conn: Connection, customer_id: int, quotation_id: str) -> QuotationRecord:
    """Owned quotations only. Someone else's id looks identical to a non-existent one."""
    stmt = select(*_Q_COLS).where(Quotation.id == quotation_id,
                                  Quotation.customer_id == customer_id,
                                  Quotation.status == "completed")
    try:
        row = conn.execute(stmt).mappings().first()
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
    stmt = select(*_Q_COLS).where(Quotation.customer_id == customer_id, Quotation.status == "completed")
    if size is not None:
        stmt = stmt.where(Quotation.frame_size == size)
    if material is not None:
        stmt = stmt.where(Quotation.frame_material == material)
    if glass is not None:
        stmt = stmt.where(Quotation.glass_type == glass)
    stmt = stmt.order_by(Quotation.created_at.desc()).limit(limit)
    return [QuotationRecord(**r) for r in conn.execute(stmt).mappings().all()]


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


def save_quotation(conn: Connection, q: NewQuotation) -> str:
    """Insert a NEW quotation row (never updates an existing one). Idempotent per key.

    A revision links to the quotation it was derived from, which must belong to the same
    customer. Call inside db_transaction() so the insert commits only if everything succeeds.
    """
    revision = 0
    if q.original_quotation_id:
        parent = get_quotation(conn, q.customer_id, q.original_quotation_id)   # ownership check
        revision = parent.revision_number + 1

    stmt = (pg_insert(Quotation)
            .values(customer_id=q.customer_id, thread_id=q.thread_id,
                    original_quotation_id=q.original_quotation_id, revision_number=revision,
                    frame_size=q.frame_size, frame_material=q.frame_material, glass_type=q.glass_type,
                    material_price=q.material_price, glass_price=q.glass_price,
                    labour_cost=q.labour_cost, wastage_rate=WASTAGE_RATE, wastage_cost=q.wastage_cost,
                    total_production_cost=q.total_production_cost, profit_margin=PROFIT_MARGIN,
                    selling_price=q.selling_price, status="completed",
                    idempotency_key=q.idempotency_key)
            .on_conflict_do_nothing(index_elements=[Quotation.idempotency_key])
            .returning(Quotation.id))
    new_id = conn.execute(stmt).scalar_one_or_none()

    if new_id is None:   # same key already saved: a retry. Return the existing row (same customer only).
        new_id = conn.execute(select(Quotation.id).where(
            Quotation.idempotency_key == q.idempotency_key,
            Quotation.customer_id == q.customer_id)).scalar_one_or_none()
        if new_id is None:
            raise PersistenceError("idempotency key conflict")
        log.info("quotation_save_deduplicated", quotation_id=new_id)
    else:
        log.info("quotation_saved", quotation_id=new_id, customer_id=q.customer_id,
                 original_quotation_id=q.original_quotation_id, revision=revision)
    return new_id