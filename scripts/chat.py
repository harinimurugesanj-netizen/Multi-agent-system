"""Console chat. Run from the project folder:
    python -m scripts.chat --customer cust-001
    python -m scripts.chat --customer cust-001 --thread <id>     # continue a conversation
"""
import argparse
import sys
import uuid

from config.config import get_settings
from app.deps import Deps
from graphs.graph import build_graph
from app.llm import get_chat_llm, get_json_llm
from config.logging_config import configure_logging
from graphs.persistence import open_persistence
from app.service import handle_message


def out(text: str) -> None:
    sys.stdout.write(text + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--customer", required=True, help="external_id of an existing customers row")
    ap.add_argument("--thread", default=None, help="reuse a thread id to continue a conversation")
    args = ap.parse_args()
    s = get_settings()
    configure_logging(s.log_level)
    thread_id = args.thread or str(uuid.uuid4())
    deps = Deps(llm_json=get_json_llm(), llm_chat=get_chat_llm(), currency=s.currency_symbol,
                max_clarifications=s.max_clarifications)
    out(f"Thread: {thread_id}   (type 'quit' to exit)")
    with open_persistence(s.database_url) as (checkpointer, store):
        graph = build_graph(deps, checkpointer, store)
        while True:
            text = input("You: ").strip()
            if text.lower() in ("quit", "exit"):
                break
            if text:
                out("Agent: " + handle_message(graph, deps, customer_external_id=args.customer,
                                               thread_id=thread_id, text=text).text)


if __name__ == "__main__":
    main()
