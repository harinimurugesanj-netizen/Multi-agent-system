import logging

from fastapi import APIRouter
from pydantic import BaseModel

from agent.main_agent import run_main_agent
from agent.sql_agent import PENDING_CONFIRMATIONS, CONFIRM_PREFIX, _format_result
from database import run_sql

logger = logging.getLogger(__name__)

ai_router = APIRouter()

class QueryRequest(BaseModel):
    query: str


class ConfirmRequest(BaseModel):
    confirmation_token: str
    confirm: bool


@ai_router.post("/ai/query")
async def ask_ai(request: QueryRequest):
    logger.info("Received /ai/query request: %r", request.query)

    try:
        response = await run_main_agent(request.query)
    except Exception:
        logger.exception("Main agent failed")
        return {
            "status": "failed",
            "message": "The agent could not complete the request.",
        }

    if not isinstance(response, dict):
        logger.error(
            "Unexpected main agent response type: %s",
            type(response).__name__,
        )
        return {
            "status": "failed",
            "message": "The agent returned an unexpected response.",
        }

    category = response.get("category", "direct")
    tools_used = []

    if category == "research":
        tools_used.append("research")
        answer = response.get("research_result", "")

    elif category == "sql":
        tools_used.append("sql_query")
        answer = response.get("sql_result", "")

    elif category == "both":
        tools_used.extend(["research", "sql_query"])

        research_result = response.get("research_result", "")
        sql_result = response.get("sql_result", "")

        if (
            isinstance(sql_result, str)
            and sql_result.startswith(CONFIRM_PREFIX)
        ):
            try:
                token, sql = sql_result[len(CONFIRM_PREFIX):].split("::", 1)
            except ValueError:
                logger.exception(
                    "Invalid DELETE confirmation response format"
                )
                return {
                    "status": "failed",
                    "message": "The SQL confirmation response was invalid.",
                }

            logger.warning(
                "DELETE awaiting confirmation (token=%s...): %s",
                token[:8],
                sql,
            )

            return {
                "status": "confirmation_required",
                "confirmation_token": token,
                "sql_preview": sql,
                "research_result": research_result,
                "message": (
                    "This will delete rows. Review the SQL and confirm to proceed."
                ),
            }

        answer = (
            f"Research Results:\n{research_result}\n\n"
            f"SQL Results:\n{sql_result}"
        )

    else:
        answer = response.get("answer", "")

    if isinstance(answer, str) and answer.startswith(CONFIRM_PREFIX):
        try:
            token, sql = answer[len(CONFIRM_PREFIX):].split("::", 1)
        except ValueError:
            logger.exception(
                "Invalid DELETE confirmation response format"
            )
            return {
                "status": "failed",
                "message": "The SQL confirmation response was invalid.",
            }

        logger.warning(
            "DELETE awaiting confirmation (token=%s...): %s",
            token[:8],
            sql,
        )

        return {
            "status": "confirmation_required",
            "confirmation_token": token,
            "sql_preview": sql,
            "message": (
                "This will delete rows. Review the SQL and confirm to proceed."
            ),
        }

    logger.info(
        "/ai/query finished: category=%s, tools_used=%s",
        category,
        tools_used,
    )

    return {
        "status": "completed",
        "answer": answer,
        "tools_used": tools_used,
    }


@ai_router.post("/ai/confirm")
def confirm_ai(request: ConfirmRequest):
    logger.info(
        "Received /ai/confirm request (token=%s..., confirm=%s)",
        request.confirmation_token[:8],
        request.confirm,
    )

    pending = PENDING_CONFIRMATIONS.pop(
        request.confirmation_token,
        None,
    )

    if pending is None:
        logger.warning(
            "Invalid or expired confirmation token (token=%s...)",
            request.confirmation_token[:8],
        )
        return {
            "status": "error",
            "message": "Invalid or expired confirmation token.",
        }

    if not request.confirm:
        logger.info(
            "DELETE cancelled by user (token=%s...)",
            request.confirmation_token[:8],
        )
        return {
            "status": "cancelled",
            "message": "DELETE cancelled. No records were deleted.",
        }

    try:
        logger.info("Executing confirmed DELETE")
        rows = run_sql(pending["sql"], is_select=False)
        logger.info("DELETE executed successfully")

    except Exception:
        logger.exception("Confirmed DELETE failed")
        return {
            "status": "failed",
            "message": "DELETE failed. Check the application logs.",
        }

    return {
        "status": "completed",
        "answer": "DELETE executed successfully.\n" + _format_result(rows),
        "sql_used": pending["sql"],
        "operation_type": "DELETE",
    }