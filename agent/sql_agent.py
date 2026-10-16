import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any, TypedDict

from langchain.agents import create_agent
from langchain.tools import tool
from langgraph.graph import END, START, StateGraph

from database import run_sql, get_schema_description

logger = logging.getLogger(__name__)

MAX_SQL_ATTEMPTS = 3          
MAX_TOOL_TRIES = 2            
MODEL = "ollama:llama3.1"

SKILL_PATH = Path(__file__).parent / "skills" / "sql-operations" / "SKILL.md"

# DELETE confirmation management (used by the /ai/confirm route).
PENDING_CONFIRMATIONS: dict[str, dict] = {}
CONFIRM_PREFIX = "CONFIRMATION_REQUIRED::"


def _is_delete(sql: str) -> bool:
    """Check whether the SQL statement is a DELETE."""
    return re.match(r"\s*delete\b", sql, re.I) is not None


def _format_result(data) -> str:
    """Format actual database results without inventing values."""
    if data is None or data == [] or data == {}:
        return "No matching records were found."
    if isinstance(data, list):
        return "\n\n".join(json.dumps(row, indent=2, default=str) for row in data)
    if isinstance(data, dict):
        return json.dumps(data, indent=2, default=str)
    return str(data)

# ------------------------------------------------------------------
# Tools (each agent only gets the tool for its own step)
# ------------------------------------------------------------------

@tool
def read_skill() -> str:
    """Read the SQL operations skill instructions."""
    try:
        text = SKILL_PATH.read_text(encoding="utf-8")
        return re.sub(r"\A---.*?---\s*", "", text, flags=re.S)  # drop frontmatter
    except OSError:
        logger.warning("Skill file not found: %s", SKILL_PATH)
        return "No skill instructions found."


@tool
def get_schema() -> str:
    """Get the live PostgreSQL database schema."""
    return get_schema_description()


@tool
def execute_sql(sql: str) -> str:
    """Execute ONE SQL statement against PostgreSQL. DELETE requires confirmation."""
    cleaned = sql.strip().rstrip(";").strip()
    logger.info("execute_sql called")

    if not cleaned:
        return json.dumps({"success": False, "sql": cleaned, "error": "Empty SQL query"})

    # Never execute DELETE without confirmation.
    if _is_delete(cleaned):
        logger.warning("DELETE query requires confirmation")
        return json.dumps({"success": False, "pending_confirmation": True, "sql": cleaned})

    try:
        is_select = re.match(r"\s*(select|with)\b", cleaned, re.I) is not None
        rows = run_sql(cleaned, is_select=is_select)
        logger.info("SQL executed successfully")
        return json.dumps({
            "success": True,
            "sql": cleaned,
            "data": rows if is_select else "Statement executed successfully.",
        }, default=str)

    except Exception as exc:
        logger.exception("SQL execution failed")
        # real database error goes back so the agent can correct the query
        return json.dumps({"success": False, "sql": cleaned, "error": str(exc)})


# ------------------------------------------------------------------
# One agent per step
# ------------------------------------------------------------------

skill_agent = create_agent(
    model=MODEL,
    tools=[read_skill],
    system_prompt="Call the read_skill tool. Do nothing else.",
)

schema_agent = create_agent(
    model=MODEL,
    tools=[get_schema],
    system_prompt="Call the get_schema tool. Do nothing else.",
)

SQL_AGENT_PROMPT = """You are a PostgreSQL expert.
You are given SKILL INSTRUCTIONS, a DATABASE SCHEMA and a USER REQUEST.
- Only use columns that belong to the specified table.
- Before generating SQL, verify that every referenced column exists
  in the table being queried.
- If a filter refers to a column in another table, use a JOIN only
  when the schema defines the appropriate relationship.
- Never invent table names or column names.
Follow the detailed SQL generation rules in the sql-operations skill.
Follow the skill instructions exactly and use only the tables and columns in the schema.
Write ONE SQL statement and call the execute_sql tool with it.
Never answer without calling execute_sql. Do not invent database results."""

sql_agent = create_agent(
    model=MODEL,
    tools=[execute_sql],
    system_prompt=SQL_AGENT_PROMPT,
)


# ------------------------------------------------------------------
# Helpers to run an agent step and read its REAL tool output
# ------------------------------------------------------------------

def _tool_output(messages, tool_name: str):
    """Return the content of the latest ToolMessage produced by `tool_name`."""
    for msg in reversed(messages):
        if getattr(msg, "name", None) == tool_name:
            content = getattr(msg, "content", None)
            if isinstance(content, str):
                return content
    return None


def _run_agent(agent, tool_name: str, prompt: str):
    """Invoke an agent; if it forgets to call its tool, ask again (bounded)."""
    for attempt in range(MAX_TOOL_TRIES):
        result = agent.invoke({"messages": [{"role": "user", "content": prompt}]})
        output = _tool_output(result.get("messages", []), tool_name)
        if output is not None:
            return output
        logger.warning("Agent did not call %s (try %d/%d)", tool_name, attempt + 1, MAX_TOOL_TRIES)
        prompt += f"\n\nYou must call the {tool_name} tool now."
    return None


# ------------------------------------------------------------------
# Graph state
# ------------------------------------------------------------------

class SQLState(TypedDict, total=False):
    query: str
    skill: str
    schema: str
    sql: str
    error: str
    attempts: int
    status: str      # success | pending_confirmation | failed
    data: Any

# ------------------------------------------------------------------
# Nodes (each node runs an agent)
# ------------------------------------------------------------------

def skill_node(state: SQLState) -> dict:
    """Step 1: the skill agent reads the skill."""
    output = _run_agent(skill_agent, "read_skill", "Read the SQL skill instructions.")
    if not output:
        return {"status": "failed", "error": "The skill agent did not read the skill."}
    logger.info("Skill loaded by skill agent")
    return {"skill": output}


def schema_node(state: SQLState) -> dict:
    """Step 2: the schema agent reads the live schema."""
    output = _run_agent(schema_agent, "get_schema", "Get the database schema.")
    if not output or not output.strip():
        return {"status": "failed", "error": "Unable to retrieve the database schema."}
    logger.info("Schema loaded by schema agent")
    return {"schema": output, "attempts": 0}


def sql_node(state: SQLState) -> dict:
    """Step 3: the SQL agent writes the SQL and executes it with execute_sql."""
    attempts = state.get("attempts", 0) + 1
    logger.info("SQL agent attempt %d of %d", attempts, MAX_SQL_ATTEMPTS)

    prompt = (
        f"SKILL INSTRUCTIONS:\n{state['skill']}\n\n"
        f"DATABASE SCHEMA:\n{state['schema']}\n\n"
        f"USER REQUEST:\n{state['query']}"
    )

    if state.get("error"):
        prompt += "\n\nYour previous attempt failed."
        if state.get("sql"):
            prompt += f"\nSQL: {state['sql']}"
        prompt += (
            f"\nError: {state['error']}"
            "\nWrite a corrected SQL statement and call execute_sql with it."
        )

    output = _run_agent(sql_agent, "execute_sql", prompt)

    if output is None:
        return {"attempts": attempts, "status": "failed",
                "error": "The SQL agent did not call execute_sql."}

    try:
        data = json.loads(output)
    except (json.JSONDecodeError, TypeError):
        return {"attempts": attempts, "status": "failed",
                "error": "Unable to read the database execution result."}

    sql = data.get("sql", state.get("sql", ""))

    if data.get("pending_confirmation") is True:
        return {"attempts": attempts, "sql": sql, "status": "pending_confirmation"}

    if data.get("success") is True:
        return {"attempts": attempts, "sql": sql, "status": "success",
                "error": "", "data": data.get("data")}

    return {"attempts": attempts, "sql": sql, "status": "failed",
            "error": data.get("error", "Unknown database error")}


# ------------------------------------------------------------------
# Routing: the graph decides the order, not the model
# ------------------------------------------------------------------

def stop_if_failed(state: SQLState) -> str:
    return "stop" if state.get("status") == "failed" else "next"


def after_sql(state: SQLState) -> str:
    if state.get("status") == "failed" and state.get("attempts", 0) < MAX_SQL_ATTEMPTS:
        return "retry"
    return "stop"


builder = StateGraph(SQLState)

builder.add_node("skill_node", skill_node)
builder.add_node("schema_node", schema_node)
builder.add_node("sql_node", sql_node)

builder.add_edge(START, "skill_node")
builder.add_conditional_edges("skill_node", stop_if_failed, {"next": "schema_node", "stop": END})
builder.add_conditional_edges("schema_node", stop_if_failed, {"next": "sql_node", "stop": END})
builder.add_conditional_edges("sql_node", after_sql, {"retry": "sql_node", "stop": END})

sql_graph = builder.compile()


# ------------------------------------------------------------------
# Tool used by the main agent
# ------------------------------------------------------------------

@tool(
    "sql_query",
    description=(
        "Answer database questions and perform database operations "
        "using the actual PostgreSQL schema and query results. "
        "Pass the user's request in plain English. Do not write SQL."
    ),
)
def call_sql_agent(query: str) -> str:
    """Run the SQL graph and return the SQL used and the actual result."""

    logger.info("Received database request")

    try:
        state = sql_graph.invoke({"query": query})
    except Exception:
        logger.exception("SQL graph failed")
        return "The SQL subagent could not complete the request."

    status = state.get("status")
    sql = state.get("sql", "")

    # DELETE: store it and let the /ai/confirm route run it
    if status == "pending_confirmation":
        token = str(uuid.uuid4())
        PENDING_CONFIRMATIONS[token] = {"sql": sql}
        logger.warning("DELETE awaiting confirmation (token=%s...): %s", token[:8], sql)
        return f"{CONFIRM_PREFIX}{token}::{sql}"

    if status == "success":
        return f"SQL: {sql}\n\n{_format_result(state.get('data'))}"

    error = state.get("error", "Unknown database error")
    if not sql:
        return error

    return (
        f"SQL: {sql}\n\n"
        f"SQL execution failed after {state.get('attempts', 0)} attempt(s): {error}"
    )