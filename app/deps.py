"""Everything the graph needs from the outside world, injected so it can be faked in tests."""
from dataclasses import dataclass
from typing import Any, Callable

from database import repository
from database.db import db_transaction
from app.retry import run_with_retry


@dataclass
class Deps:
    llm_json: Any                              # strict-JSON Qwen3 (classification / extraction)
    llm_chat: Any                              # conversational Qwen3 (tool calling, final reply)
    repo: Any = repository                     # module or fake exposing the repository functions
    tx: Callable = db_transaction              # context manager yielding a connection
    currency: str = ""
    max_clarifications: int = 3
    retry_delay: float = 0.3
    default_customer: str | None = None        

    def db(self, fn: Callable[[Any], Any]) -> Any:
        """Run fn(conn) in ONE transaction, retrying brief connection failures."""
        def attempt():
            with self.tx() as conn:
                return fn(conn)
        return run_with_retry(attempt, delay=self.retry_delay)
