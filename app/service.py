from dataclasses import dataclass

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from app.errors import AppError
from config.logging_config import get_logger

log = get_logger(__name__)


@dataclass
class Reply:
    text: str
    awaiting_input: bool = False      # True when `text` is a question the customer must answer


def handle_message(graph, deps, *, customer_external_id: str, thread_id: str, text: str) -> Reply:
    cfg = {"configurable": {"thread_id": thread_id, "customer_external_id": customer_external_id}}
    try:
        def verify(conn):
            cid = deps.repo.get_customer_id(conn, customer_external_id)
            deps.repo.claim_or_verify_thread(conn, thread_id, cid)
        deps.db(verify)

        snapshot = graph.get_state(cfg)
        pending = any(getattr(t, "interrupts", None) for t in snapshot.tasks)
        payload = Command(resume=text) if pending else {"messages": [HumanMessage(content=text)]}
        result = graph.invoke(payload, cfg)
    except AppError as exc:
        log.warning("request_rejected", code=exc.code, thread_id=thread_id)
        return Reply(exc.safe_message)
    except Exception:
        log.exception("request_failed", thread_id=thread_id)
        return Reply(AppError.safe_message)

    interrupts = result.get("__interrupt__")
    if interrupts:
        return Reply(interrupts[0].value["question"], awaiting_input=True)
    return Reply(str(result["messages"][-1].content))
