"""Studio/`langgraph dev` persistence backed by YOUR PostgreSQL database.
The server needs async context managers that yield the saver / store."""
import asyncio
import contextlib
import sys

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore

from config.config import get_settings


def _check_event_loop() -> None:
    loop = asyncio.get_running_loop()
    if sys.platform == "win32" and type(loop).__name__ == "ProactorEventLoop":
        raise RuntimeError(
            "Async psycopg cannot run on Windows' default ProactorEventLoop. "
            "See the notes on this limitation; use scripts.chat for Postgres persistence instead.")


@contextlib.asynccontextmanager
async def generate_checkpointer():
    _check_event_loop()
    async with AsyncPostgresSaver.from_conn_string(get_settings().database_url) as saver:
        await saver.setup()
        yield saver


@contextlib.asynccontextmanager
async def generate_store():
    _check_event_loop()
    async with AsyncPostgresStore.from_conn_string(get_settings().database_url) as store:
        await store.setup()
        yield store