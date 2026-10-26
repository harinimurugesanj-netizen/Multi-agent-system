from config.config import get_settings
from app.deps import Deps
from graphs.graph import build_graph
from app.llm import get_chat_llm, get_json_llm
from config.logging_config import configure_logging

_s = get_settings()
configure_logging(_s.log_level)

graph = build_graph(
    Deps(llm_json=get_json_llm(), llm_chat=get_chat_llm(), currency=_s.currency_symbol,
         max_clarifications=_s.max_clarifications, default_customer=_s.studio_customer_id),
    checkpointer=None, store=None)