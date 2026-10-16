import logging
from sqlalchemy import inspect
from sqlalchemy import inspect, text 
from database.db_connection import engine, SessionLocal
MAX_ROWS = 500

logger = logging.getLogger(__name__)
def get_schema_description() -> str:
    """Introspect the database and return table/column/foreign-key info as text."""
    inspector = inspect(engine)
    tables = inspector.get_table_names(schema="public")

    sections = []
    for table in tables:
        columns = inspector.get_columns(table, schema="public")
        col_lines = [f"  - {c['name']} ({c['type']})" for c in columns]

        fks = inspector.get_foreign_keys(table, schema="public")
        fk_lines = [
            f"  FK: {fk['constrained_columns'][0]} -> {fk['referred_table']}.{fk['referred_columns'][0]}"
            for fk in fks
        ]

        sections.append("\n".join([f"Table: {table}", *col_lines, *fk_lines]))

    return "\n\n".join(sections)


def run_sql(sql: str, is_select: bool, params: dict | None = None):
    """Run SQL in its own session. Returns rows (as dicts, capped at MAX_ROWS) for SELECT, None for writes."""
    session = SessionLocal()
    try:
        result = session.execute(text(sql), params or {})
        rows = [dict(r) for r in result.mappings()] if result.returns_rows else None
        session.commit()
        return rows[:MAX_ROWS] if rows is not None else None
    except Exception:
        logger.exception("SQL execution failed")
        session.rollback()
        raise
    finally:
        session.close()