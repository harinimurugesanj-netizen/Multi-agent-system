"""Conditional routing functions. They only READ state and return the next node's name."""
from typing import Any, Literal, Mapping

from app.constants import MAX_REPAIRS
from config.logging_config import get_logger

log = get_logger(__name__)
State = Mapping[str, Any]


def route_after_context(state: State) -> Literal["respond_error", "classify_intent"]:
    return "respond_error" if state.get("error_code") else "classify_intent"


def route_by_intent(state: State) -> Literal["respond_error", "apply_requested", "find_quotations", "general_agent"]:
    if state.get("error_code"):
        return "respond_error"
    intent = state.get("intent")
    if intent == "new_quotation":
        return "apply_requested"
    if intent in ("modify_quotation", "retrieve_quotation"):
        return "find_quotations"
    return "general_agent"


def route_after_lookup(state: State) -> Literal["respond_error", "present_history", "load_base_requirements", "ask_which_quotation"]:
    if state.get("error_code"):
        return "respond_error"
    if state.get("intent") == "retrieve_quotation":
        return "present_history"                      # answer straight away: one record or a list
    if state.get("selected_quotation_id"):
        return "load_base_requirements"
    return "ask_which_quotation"                      # several matches: customer must choose


def route_after_base(state: State) -> Literal["respond_error", "apply_requested"]:
    return "respond_error" if state.get("error_code") else "apply_requested"


def route_after_apply(state: State) -> Literal["ask_change_details", "validate_requirements"]:
    if state.get("intent") == "modify_quotation" and not state.get("requested_changes"):
        return "ask_change_details"                   # modify with nothing to modify yet
    return "validate_requirements"


def route_after_validation(state: State) -> Literal["respond_error", "repair_requirements", "ask_customer", "fetch_prices"]:
    if state.get("error_code"):
        return "respond_error"
    status = state.get("validation_status")
    if status == "valid":
        return "fetch_prices"
    if status not in ("missing", "invalid"):
        log.warning("unexpected_validation_status", status=status)   # never price on unknown status
        return "ask_customer"
    attempts = state.get("repair_attempts", 0)
    # Send the problems back to the LLM: up to MAX_REPAIRS times for values that are not offered,
    # and once for fields that are only missing. Then ask the customer.
    if attempts < MAX_REPAIRS and (state.get("invalid_fields") or attempts == 0):
        return "repair_requirements"
    return "ask_customer"


def route_after_price_fetch(state: State) -> Literal["respond_error", "calculate_estimation"]:
    return "respond_error" if state.get("error_code") else "calculate_estimation"


def route_after_estimation(state: State) -> Literal["respond_error", "save_quotation"]:
    return "respond_error" if state.get("error_code") else "save_quotation"


def route_after_save(state: State) -> Literal["respond_error", "save_memory"]:
    return "respond_error" if state.get("error_code") or not state.get("quotation_id") else "save_memory"