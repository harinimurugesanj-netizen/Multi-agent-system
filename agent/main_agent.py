import asyncio
import json
import logging

from langchain.agents import create_agent
from langchain.tools import tool

from agent.research_agent import call_research_agent
from agent.sql_agent import call_sql_agent, CONFIRM_PREFIX

logger = logging.getLogger(__name__)

MODEL = "ollama:llama3.1"


@tool
async def parallel_agents(query: str) -> str:
    """Run the research and SQL agents concurrently when both are required."""

    logger.info("Starting parallel research and SQL execution")

    try:
        research_task = asyncio.to_thread(
            call_research_agent.invoke,
            {"query": query},
        )

        sql_task = asyncio.to_thread(
            call_sql_agent.invoke,
            {"query": query},
        )

        research_result, sql_result = await asyncio.gather(
            research_task,
            sql_task,
            return_exceptions=True,
        )

        if isinstance(research_result, Exception):
            logger.error("Research agent failed: %s", research_result)
            research_result = "Research agent execution failed."

        if isinstance(sql_result, Exception):
            logger.error("SQL agent failed: %s", sql_result)
            sql_result = "SQL agent execution failed."

        results = {
            "research_result": str(research_result),
            "sql_result": str(sql_result),
        }

        logger.info("Parallel research and SQL execution completed")

        return json.dumps(results)

    except Exception:
        logger.exception("Parallel agent execution failed")
        return json.dumps({
            "research_result": "Research execution failed.",
            "sql_result": "SQL execution failed.",
        })


main_agent = create_agent(
    model=MODEL,
    tools=[
        call_research_agent,
        call_sql_agent,
        parallel_agents,
    ],
    system_prompt=(
        "You are the main supervisor agent. Understand the user's intent "
        "and choose the appropriate execution path.\n\n"

        "TOOL SELECTION:\n"
        "1. For greetings and general questions that require neither "
        "research nor database access, answer directly.\n"
        "2. For requests requiring only web research, call "
        "call_research_agent.\n"
        "3. For requests requiring only database operations, call "
        "call_sql_agent.\n"
        "4. For requests requiring both web research and database access, "
        "call parallel_agents exactly once.\n\n"

        "TOOL RULES:\n"
        "Pass the user's original request to the selected tool. "
        "When both agents are required, do not call the research and SQL "
        "tools separately. Use parallel_agents. Never invent tool results "
        "or claim an operation succeeded without evidence. "
        "If SQL requires DELETE confirmation, do not claim the deletion "
        "has already been executed.\n\n"

        "FINAL RESPONSE:\n"
        "After receiving the tool results, respond clearly and accurately."
    ),
)


async def run_main_agent(query: str) -> dict:
    """Run the supervisor once and return its actual results."""

    logger.info("Received user query")

    response = await main_agent.ainvoke({
        "messages": [
            {"role": "user", "content": query}
        ]
    })

    messages = response.get("messages", [])
    requested_tools = []
    tool_results = {}

    for message in messages:
        for tool_call in getattr(message, "tool_calls", []) or []:
            requested_tools.append(tool_call.get("name"))

        message_name = getattr(message, "name", None)
        message_content = getattr(message, "content", None)

        if message_name and isinstance(message_content, str):
            tool_results[message_name] = message_content

    logger.info("Supervisor selected tools: %s", requested_tools)

    # Both agents were already executed by the parallel_agents tool.
    if "parallel_agents" in requested_tools:
        parallel_result = tool_results.get("parallel_agents", "")

        try:
            results = json.loads(parallel_result)
        except json.JSONDecodeError:
            logger.exception("Could not parse parallel agent results")
            return {
                "category": "both",
                "research_result": "",
                "sql_result": "Could not parse parallel agent results.",
            }

        return {
            "category": "both",
            "research_result": results.get("research_result", ""),
            "sql_result": results.get("sql_result", ""),
        }

    # Research and SQL were selected individually.
    if (
        "call_research_agent" in requested_tools
        and "call_sql_agent" in requested_tools
    ):
        return {
            "category": "both",
            "research_result": tool_results.get(
                "research",
                tool_results.get("call_research_agent", ""),
            ),
            "sql_result": tool_results.get(
                "sql_query",
                tool_results.get("call_sql_agent", ""),
            ),
        }

    if "call_research_agent" in requested_tools:
        return {
            "category": "research",
            "research_result": tool_results.get(
                "research",
                tool_results.get("call_research_agent", ""),
            ),
        }

    if "call_sql_agent" in requested_tools:
        return {
            "category": "sql",
            "sql_result": tool_results.get(
                "sql_query",
                tool_results.get("call_sql_agent", ""),
            ),
        }

    # No tool was selected, so return the supervisor's direct response.
    final_answer = ""

    for message in reversed(messages):
        if (
            getattr(message, "type", None) == "ai"
            and isinstance(getattr(message, "content", None), str)
        ):
            final_answer = message.content
            break

    return {
        "category": "direct",
        "answer": final_answer,
    }