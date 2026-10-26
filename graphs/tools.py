"""LangChain tools for the general-questions branch (executed by LangGraph's ToolNode)."""
from langchain_core.tools import tool


def make_tools(deps):
    @tool
    def list_available_options() -> dict:
        """List the frame sizes, frame materials and glass types the shop offers."""
        return deps.db(lambda conn: deps.repo.list_options(conn))

    return [list_available_options]
