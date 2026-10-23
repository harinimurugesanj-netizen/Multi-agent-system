from typing import Annotated, Any, Optional, TypedDict

from langgraph.graph.message import add_messages
from langchain_core.messages import AnyMessage

class QuotationState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
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
    "candidates": [], "selected_quotation_id": None, "original_quotation_id": None,
    "quotation_id": None, "material_price": None, "glass_price": None, "labour_cost": None,
    "wastage_cost": None, "total_production_cost": None, "profit_margin": None,
    "selling_price": None, "clarification_attempts": 0, "error_code": None, "error": None,
}
