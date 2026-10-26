"""Typed LangGraph state.

Nodes return ONLY the keys they change; LangGraph overwrites per key, so untouched keys keep
their value (this is how size/material survive when the customer only supplies glass).
Money is stored as strings (e.g. "218.89") so checkpoints serialise safely; calculation
nodes convert to Decimal. `FRESH_REQUEST` is applied at the start of every new customer
request so one quotation never leaks into the next in the same thread.
"""
from typing import Annotated, Any, Optional, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class QuotationState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]      # list[AnyMessage] lets Studio offer Chat mode
    intent: Optional[str]                       # new_quotation | modify_quotation | retrieve_quotation | general_question

    # Trusted identity: set by load_context from the DB, never by the LLM.
    customer_id: int
    thread_id: str
    run_id: str                                 # idempotency key part
    memory_summary: str                         # from PostgresStore

    # Requirements (None = not provided; never defaulted).
    frame_size: Optional[str]
    frame_material: Optional[str]
    glass_type: Optional[str]
    missing_fields: list[str]
    invalid_fields: dict[str, str]
    validation_status: str                      # pending | valid | missing | invalid

    # Understanding of the message.
    catalog: dict                               # options + valid combinations, read from the DB
    problems: list[str]                         # validation problems (also sent to the LLM to repair)
    repair_attempts: int
    reference_latest: bool                      # customer pointed at their most recent quotation
    requested_changes: dict[str, str]           # values the customer asked for
    quotation_reference: dict[str, str]         # attributes identifying WHICH old quotation

    # Quotation lookup / linkage.
    candidates: list[dict]
    selected_quotation_id: Optional[str]
    original_quotation_id: Optional[str]
    base_requirements: dict[str, str]           # requirements of the quotation being modified
    quotation_id: Optional[str]

    # Pricing (strings).
    material_price: Optional[str]
    glass_price: Optional[str]
    labour_cost: Optional[str]
    wastage_cost: Optional[str]
    total_production_cost: Optional[str]
    profit_margin: Optional[str]
    selling_price: Optional[str]

    clarification_attempts: int
    error_code: Optional[str]
    error: Optional[str]


FRESH_REQUEST: dict[str, Any] = {
    "intent": None, "frame_size": None, "frame_material": None, "glass_type": None,
    "missing_fields": [], "invalid_fields": {}, "validation_status": "pending",
    "requested_changes": {}, "quotation_reference": {}, "base_requirements": {},
    "catalog": {}, "problems": [], "repair_attempts": 0, "reference_latest": False,
    "candidates": [], "selected_quotation_id": None, "original_quotation_id": None,
    "quotation_id": None, "material_price": None, "glass_price": None, "labour_cost": None,
    "wastage_cost": None, "total_production_cost": None, "profit_margin": None,
    "selling_price": None, "clarification_attempts": 0, "error_code": None, "error": None,
}