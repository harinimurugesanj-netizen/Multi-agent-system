"""LangGraph nodes. Each returns ONLY the state keys it changes (or a Command).

Nodes that call interrupt() do NOTHING with side effects before it: on resume LangGraph
re-runs the node from the top and interrupt() returns the customer's reply.
"""
import json
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore
from langgraph.types import Command, interrupt

from app.classify import classify_message
from app.constants import REQUIREMENT_FIELDS
from app.errors import AppError, LLMUnavailable, safe_message_for
from app.estimation import Estimation, calculate_estimation, validate_estimation
from app.extraction import extract_from_message, repair_from_message
from app.formatting import (describe_items, fallback_response, fmt_money, quotation_text,
                            short_ref, verify_response)
from config.logging_config import get_logger
from app.questions import build_question
from app.quotation_select import (choose_quotation, format_candidates, record_to_candidate,
                                  resolve_reply)
from app.requirements import merge_requirements, validate_against_catalog
from graphs.state import FRESH_REQUEST, QuotationState

log = get_logger(__name__)

GENERAL_PROMPT = (
    "You are a friendly assistant for a photo-frame shop. Use the list_available_options tool "
    "to answer questions about frame sizes, materials and glass types. Never state prices. If "
    "the customer wants a price, ask them to describe the frame they want (size, material and "
    "glass type) so you can prepare a quotation. Do not invent information.")

RESPONSE_PROMPT = (
    "You are a friendly photo-frame shop assistant. Write a short reply (2-4 sentences) "
    "presenting the customer's quotation from the JSON facts. Mention the selected items and "
    "the total exactly as given. Do not mention any other numbers, costs, discounts or margins. "
    "If is_revision is true, say it is a revised quotation and that the original is unchanged.")


def _last_human_text(state: QuotationState) -> str:
    for m in reversed(state.get("messages", [])):
        if isinstance(m, HumanMessage):
            return str(m.content)
    return ""


def _reply_text(reply: Any) -> str:
    """Resume payload may be a plain string, or a dict (e.g. from Studio): take the text."""
    if isinstance(reply, dict):
        for key in ("reply", "text", "content", "value", "message"):
            if isinstance(reply.get(key), str):
                return reply[key]
        return ""
    return reply if isinstance(reply, str) else str(reply)


def _try_db(deps, fn):
    """Run a DB operation; return (result, None) or (None, error-state-update)."""
    try:
        return deps.db(fn), None
    except AppError as exc:
        log.warning("node_db_error", code=exc.code, detail=exc.detail[:200])
        return None, {"error_code": exc.code, "error": exc.detail}
    except Exception:
        log.exception("node_unexpected_error")
        return None, {"error_code": "internal_error", "error": "unexpected error"}


def make_nodes(deps, tools) -> dict[str, Any]:
    cur = deps.currency
    repo = deps.repo
    llm_with_tools = deps.llm_chat.bind_tools(tools)

    # ------------------------------------------------------------ entry
    def load_context(state: QuotationState, config: RunnableConfig, *, store: BaseStore | None = None):
        """Identify + authorise the customer, reset per-request state, load memory."""
        cfg = (config or {}).get("configurable", {})
        ext, thread_id = cfg.get("customer_external_id") or deps.default_customer, cfg.get("thread_id")
        if not ext or not thread_id:
            return {**FRESH_REQUEST, "error_code": "unauthorized", "error": "missing identity"}

        def work(conn):
            cid = repo.get_customer_id(conn, ext)
            repo.claim_or_verify_thread(conn, thread_id, cid)
            return cid
        cid, err = _try_db(deps, work)
        if err:
            return {**FRESH_REQUEST, **err}

        catalog, err = _try_db(deps, lambda conn: repo.get_catalog(conn))
        if err:
            return {**FRESH_REQUEST, **err}

        summary = ""
        if store is not None:
            try:
                items = store.search(("customers", str(cid), "quotations"), limit=5)
                items = sorted(items, key=lambda i: i.value.get("saved_at", ""), reverse=True)
                summary = "\n".join(f"- {i.value['summary']}" for i in items)
            except Exception:
                log.warning("memory_load_failed", exc_info=True)
        return {**FRESH_REQUEST, "customer_id": cid, "thread_id": thread_id,
                "run_id": uuid.uuid4().hex, "memory_summary": summary, "catalog": catalog}

    def classify_intent(state: QuotationState):
        try:
            c = classify_message(deps.llm_json, _last_human_text(state), state.get("catalog") or {})
        except LLMUnavailable as exc:
            return {"error_code": exc.code, "error": exc.detail}
        return {"intent": c.intent, "requested_changes": c.requested, "quotation_reference": c.reference,
                "reference_latest": c.reference_latest}

    # ------------------------------------------------------------ general questions
    def general_agent(state: QuotationState):
        history = list(state.get("messages", []))[-8:]
        while history and getattr(history[0], "type", "") == "tool":   # never start mid tool-call
            history.pop(0)
        system = GENERAL_PROMPT
        if state.get("memory_summary"):
            system += "\nCustomer's recent quotations (for context):\n" + state["memory_summary"]
        try:
            return {"messages": [llm_with_tools.invoke([SystemMessage(content=system), *history])]}
        except Exception:
            log.exception("general_agent_failed")
            return {"messages": [AIMessage(content=safe_message_for("llm_unavailable"))]}

    # ------------------------------------------------------------ quotation lookup (modify / retrieve)
    def find_quotations(state: QuotationState):
        ref = state.get("quotation_reference") or {}
        records, err = _try_db(deps, lambda conn: repo.find_quotations(
            conn, state["customer_id"], size=ref.get("frame_size"),
            material=ref.get("frame_material"), glass=ref.get("glass_type"), limit=5))
        if err:
            return err
        if not records:
            return {"error_code": "quotation_not_found", "error": "no matching quotation"}
        cands = [record_to_candidate(r) for r in records]
        return {"candidates": cands, "selected_quotation_id": choose_quotation(cands, state.get("reference_latest", False))}

    def ask_which_quotation(state: QuotationState) -> Command[Literal["load_base_requirements", "ask_which_quotation", "respond_error"]]:
        attempts = state.get("clarification_attempts", 0)
        if attempts >= deps.max_clarifications:
            return Command(update={"error_code": "too_many_clarifications"}, goto="respond_error")
        cands = state["candidates"]
        question = ("I found several quotations on your account. Which one do you mean? "
                    "Reply with its number:\n" + format_candidates(cands, cur))
        reply = _reply_text(interrupt({"type": "choose_quotation", "question": question}))
        msgs = [AIMessage(content=question), HumanMessage(content=reply)]
        chosen = resolve_reply(deps.llm_json, cands, reply, cur)
        if chosen:
            return Command(update={"messages": msgs, "selected_quotation_id": chosen}, goto="load_base_requirements")
        return Command(update={"messages": msgs, "clarification_attempts": attempts + 1}, goto="ask_which_quotation")

    def load_base_requirements(state: QuotationState):
        """Copy size/material/glass from the chosen quotation (ownership-checked in SQL)."""
        qid = state["selected_quotation_id"]
        rec, err = _try_db(deps, lambda conn: repo.get_quotation(conn, state["customer_id"], qid))
        if err:
            return err
        base = {"frame_size": rec.frame_size, "frame_material": rec.frame_material, "glass_type": rec.glass_type}
        return {**base, "base_requirements": base, "original_quotation_id": qid}

    def present_history(state: QuotationState):
        """History question: answer from PostgreSQL immediately. No pricing, no recalculation."""
        qid = state.get("selected_quotation_id")
        if qid:
            rec, err = _try_db(deps, lambda conn: repo.get_quotation(conn, state["customer_id"], qid))
            if err:
                return {"messages": [AIMessage(content=safe_message_for(err["error_code"]))]}
            return {"messages": [AIMessage(content=quotation_text(record_to_candidate(rec), cur))]}
        text = ("Here are your most recent quotations:\n" + format_candidates(state["candidates"], cur)
                + "\nAsk me about a specific one, for example \"my 5x7 quotation\".")
        return {"messages": [AIMessage(content=text)]}

    # ------------------------------------------------------------ requirements
    def apply_requested(state: QuotationState):
        """Merge what the customer asked for into the requirements (overwrite on change)."""
        current = {f: state.get(f) for f in REQUIREMENT_FIELDS}
        return merge_requirements(current, state.get("requested_changes") or {}) or {"error": None}

    def ask_change_details(state: QuotationState) -> Command[Literal["extract_requirements", "respond_error"]]:
        attempts = state.get("clarification_attempts", 0)
        if attempts >= deps.max_clarifications:
            return Command(update={"error_code": "too_many_clarifications"}, goto="respond_error")
        question = "What would you like to change on that quotation: the frame size, frame material or glass type?"
        reply = _reply_text(interrupt({"type": "change_details", "question": question}))
        return Command(update={"messages": [AIMessage(content=question), HumanMessage(content=reply)],
                               "clarification_attempts": attempts + 1}, goto="extract_requirements")

    def extract_requirements(state: QuotationState):
        """Read the customer's reply (LLM) and merge it into the requirements."""
        text = _last_human_text(state)
        collected = {f: state.get(f) for f in REQUIREMENT_FIELDS}
        asked = list(state.get("missing_fields", [])) + list(state.get("invalid_fields", {}))
        result = extract_from_message(deps.llm_json, text, state.get("catalog") or {}, asked)
        return {**merge_requirements(collected, result.fields), "repair_attempts": 0, "error": None}

    def validate_requirements_node(state: QuotationState):
        """Validate the JSON against what the DATABASE offers (values and price combinations)."""
        catalog, err = _try_db(deps, lambda conn: repo.get_catalog(conn))
        if err:
            return err
        result = validate_against_catalog(state, catalog)
        log.info("validate_node", thread_id=state.get("thread_id"), status=result["validation_status"],
                 missing=result["missing_fields"], invalid=result["invalid_fields"])
        return {**result, "catalog": catalog}

    def repair_requirements(state: QuotationState):
        """Send the validation problems back to the LLM so it can correct its JSON."""
        current = {f: state.get(f) for f in REQUIREMENT_FIELDS}
        result = repair_from_message(deps.llm_json, _last_human_text(state), current,
                                     state.get("problems", []), state.get("catalog") or {})
        log.info("repair_node", attempt=state.get("repair_attempts", 0) + 1, fixed=result.fields)
        return {**merge_requirements(current, result.fields),
                "repair_attempts": state.get("repair_attempts", 0) + 1}

    def ask_customer(state: QuotationState) -> Command[Literal["extract_requirements", "respond_error"]]:
        attempts = state.get("clarification_attempts", 0)
        if attempts >= deps.max_clarifications:
            return Command(update={"error_code": "too_many_clarifications"}, goto="respond_error")
        question = build_question(state.get("missing_fields", []), state.get("invalid_fields", {}),
                                  state.get("problems", []), state.get("catalog") or {})
        reply = _reply_text(interrupt({"type": "clarification", "question": question,
                                       "missing_fields": state.get("missing_fields", []),
                                       "invalid_fields": state.get("invalid_fields", {})}))
        return Command(update={"messages": [AIMessage(content=question), HumanMessage(content=reply)],
                               "clarification_attempts": attempts + 1}, goto="extract_requirements")

    # ------------------------------------------------------------ pricing & estimation
    def fetch_prices(state: QuotationState):
        b, err = _try_db(deps, lambda conn: repo.fetch_prices(
            conn, state["frame_size"], state["frame_material"], state["glass_type"]))
        if err:
            return err
        return {"material_price": str(b.material_price), "glass_price": str(b.glass_price),
                "labour_cost": str(b.labour_cost)}

    def calculate_estimation_node(state: QuotationState):
        e = calculate_estimation(Decimal(state["material_price"]), Decimal(state["glass_price"]),
                                 Decimal(state["labour_cost"]))
        return {"wastage_cost": str(e.wastage_cost), "total_production_cost": str(e.total_production_cost),
                "profit_margin": str(e.profit_margin), "selling_price": str(e.selling_price)}

    def validate_estimation_node(state: QuotationState):
        try:
            est = Estimation(*(Decimal(state[k]) for k in (
                "material_price", "glass_price", "labour_cost", "wastage_cost",
                "total_production_cost", "profit_margin", "selling_price")))
        except Exception:
            return {"error_code": "invalid_estimation", "error": "missing or malformed price data"}
        problems = validate_estimation(est)
        if problems:
            log.error("estimation_invalid", problems=problems, thread_id=state.get("thread_id"))
            return {"error_code": "invalid_estimation", "error": "; ".join(problems)}
        base = state.get("base_requirements")
        if base and all(state.get(f) == base.get(f) for f in REQUIREMENT_FIELDS):
            return {"error_code": "no_change", "error": "identical to original"}
        return {"error": None}

    def save_quotation(state: QuotationState):
        q = repo.NewQuotation(
            customer_id=state["customer_id"], thread_id=state["thread_id"],
            frame_size=state["frame_size"], frame_material=state["frame_material"],
            glass_type=state["glass_type"],
            material_price=Decimal(state["material_price"]), glass_price=Decimal(state["glass_price"]),
            labour_cost=Decimal(state["labour_cost"]), wastage_cost=Decimal(state["wastage_cost"]),
            total_production_cost=Decimal(state["total_production_cost"]),
            selling_price=Decimal(state["selling_price"]),
            idempotency_key=f"{state['thread_id']}:{state['run_id']}",
            original_quotation_id=state.get("original_quotation_id"))
        qid, err = _try_db(deps, lambda conn: repo.save_quotation(conn, q))
        return err if err else {"quotation_id": qid}

    def save_memory(state: QuotationState, *, store: BaseStore | None = None):
        """Explicit cross-thread memory write. A failure here must NOT undo the saved quotation."""
        if store is not None:
            try:
                now = datetime.now(timezone.utc).isoformat()
                summary = (f"{describe_items(state['frame_size'], state['frame_material'], state['glass_type'])}, "
                           f"total {fmt_money(state['selling_price'], cur)} (ref {short_ref(state['quotation_id'])})")
                cid = str(state["customer_id"])
                store.put(("customers", cid, "quotations"), state["quotation_id"],
                          {"summary": summary, "saved_at": now, "thread_id": state["thread_id"],
                           "original_quotation_id": state.get("original_quotation_id")})
                store.put(("customers", cid, "threads"), state["thread_id"],
                          {"last_quotation_id": state["quotation_id"], "updated_at": now})
            except Exception:
                log.warning("memory_save_failed", exc_info=True)
        return {"error": None}

    def generate_response(state: QuotationState):
        size, material, glass = state["frame_size"], state["frame_material"], state["glass_type"]
        price, is_rev = state["selling_price"], bool(state.get("original_quotation_id"))
        facts = {"items": describe_items(size, material, glass), "total": fmt_money(price, cur), "is_revision": is_rev}
        text = None
        try:
            raw = deps.llm_chat.invoke([SystemMessage(content=RESPONSE_PROMPT),
                                        HumanMessage(content=json.dumps(facts, ensure_ascii=False))]).content
            cand = re.sub(r"<think>.*?</think>", "", str(raw), flags=re.S).strip()
            if cand and verify_response(cand, price, size):
                text = cand
            else:
                log.warning("llm_response_rejected", reason="numbers did not match saved quotation")
        except Exception:
            log.exception("llm_response_failed")
        if text is None:
            text = fallback_response(size, material, glass, price, cur, is_rev)
        text += f"\nQuotation reference: {short_ref(state['quotation_id'])}"
        return {"messages": [AIMessage(content=text)]}

    def respond_error(state: QuotationState):
        log.info("responding_with_error", code=state.get("error_code"), thread_id=state.get("thread_id"))
        return {"messages": [AIMessage(content=safe_message_for(state.get("error_code")))]}

    return {
        "load_context": load_context, "classify_intent": classify_intent, "general_agent": general_agent,
        "find_quotations": find_quotations, "ask_which_quotation": ask_which_quotation,
        "load_base_requirements": load_base_requirements, "present_history": present_history,
        "apply_requested": apply_requested, "ask_change_details": ask_change_details,
        "extract_requirements": extract_requirements, "validate_requirements": validate_requirements_node,
        "repair_requirements": repair_requirements,
        "ask_customer": ask_customer, "fetch_prices": fetch_prices,
        "calculate_estimation": calculate_estimation_node, "validate_estimation": validate_estimation_node,
        "save_quotation": save_quotation, "save_memory": save_memory,
        "generate_response": generate_response, "respond_error": respond_error,
    }