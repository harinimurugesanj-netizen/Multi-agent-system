"""Stage 6: PostgresSaver (graph state per thread) + PostgresStore (cross-thread memory).

Both live in the SAME database as the business tables. setup() creates their own tables
(checkpoints*, store*) and is safe to call on every start.
"""
from contextlib import contextmanager
from typing import Iterator

from config.logging_config import get_logger

log = get_logger(__name__)


@contextmanager
def open_persistence(database_url: str) -> Iterator[tuple]:
    from langgraph.checkpoint.postgres import PostgresSaver
    from langgraph.store.postgres import PostgresStore
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    # autocommit + dict_row are REQUIRED by the LangGraph Postgres integrations.
    pool = ConnectionPool(conninfo=database_url, max_size=10, open=True,
                          kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row})
    try:
        checkpointer = PostgresSaver(pool)
        checkpointer.setup()
        store = PostgresStore(pool)
        store.setup()
        log.info("persistence_ready")
        yield checkpointer, store
    finally:
        pool.close()
