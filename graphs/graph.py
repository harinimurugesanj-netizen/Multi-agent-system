"""Graph wiring. See README for the diagram."""
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from graphs.nodes import make_nodes
from graphs.routing import (route_after_apply, route_after_base, route_after_context,
                         route_after_estimation, route_after_lookup, route_after_price_fetch,
                         route_after_save, route_after_validation, route_by_intent)
from graphs.state import QuotationState
from graphs.tools import make_tools


def build_graph(deps, checkpointer, store=None):
    """A checkpointer is mandatory: interrupt()/resume needs persisted state."""
    tools = make_tools(deps)
    n = make_nodes(deps, tools)
    b = StateGraph(QuotationState)

    for name, fn in n.items():
        if name in ("ask_customer", "ask_change_details"):
            b.add_node(name, fn, destinations=("extract_requirements", "respond_error"))
        elif name == "ask_which_quotation":
            b.add_node(name, fn, destinations=("load_base_requirements", "ask_which_quotation", "respond_error"))
        else:
            b.add_node(name, fn)
    b.add_node("tools", ToolNode(tools))

    b.add_edge(START, "load_context")
    b.add_conditional_edges("load_context", route_after_context,
                            {"respond_error": "respond_error", "classify_intent": "classify_intent"})
    b.add_conditional_edges("classify_intent", route_by_intent, {
        "respond_error": "respond_error", "apply_requested": "apply_requested",
        "find_quotations": "find_quotations", "general_agent": "general_agent"})

    # general questions: LLM <-> ToolNode loop
    b.add_conditional_edges("general_agent", tools_condition, {"tools": "tools", END: END})
    b.add_edge("tools", "general_agent")

    # history / modification lookup
    b.add_conditional_edges("find_quotations", route_after_lookup, {
        "respond_error": "respond_error", "present_history": "present_history",
        "load_base_requirements": "load_base_requirements", "ask_which_quotation": "ask_which_quotation"})
    b.add_conditional_edges("load_base_requirements", route_after_base,
                            {"respond_error": "respond_error", "apply_requested": "apply_requested"})
    b.add_edge("present_history", END)

    # requirements collection (shared by new + modify)
    b.add_conditional_edges("apply_requested", route_after_apply, {
        "ask_change_details": "ask_change_details", "validate_requirements": "validate_requirements"})
    b.add_edge("extract_requirements", "validate_requirements")
    b.add_conditional_edges("validate_requirements", route_after_validation,
                            {"ask_customer": "ask_customer", "fetch_prices": "fetch_prices"})

    # pricing -> estimation -> save -> reply (shared by new + modify)
    b.add_conditional_edges("fetch_prices", route_after_price_fetch,
                            {"respond_error": "respond_error", "calculate_estimation": "calculate_estimation"})
    b.add_edge("calculate_estimation", "validate_estimation")
    b.add_conditional_edges("validate_estimation", route_after_estimation,
                            {"respond_error": "respond_error", "save_quotation": "save_quotation"})
    b.add_conditional_edges("save_quotation", route_after_save,
                            {"respond_error": "respond_error", "save_memory": "save_memory"})
    b.add_edge("save_memory", "generate_response")
    b.add_edge("generate_response", END)
    b.add_edge("respond_error", END)
    return b.compile(checkpointer=checkpointer, store=store)
