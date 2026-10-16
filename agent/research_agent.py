import logging

from ddgs import DDGS
from langchain.tools import tool
from langchain.agents import create_agent

logger = logging.getLogger(__name__)


@tool
def web_search(query: str) -> str:
    """Search the web and return titles, text snippets, and URLs."""
    logger.info("Searching the web for: %s", query)

    try:
        results = DDGS().text(query, max_results=5)

        if not results:
            logger.warning("No results found")
            return "No search results found."

        formatted_results = []
        for index, result in enumerate(results, start=1):
            title = result.get("title", "No title")
            snippet = result.get("body", "No snippet")
            formatted_results.append(
                f"Result {index}\nTitle: {title}\nSnippet: {snippet}\n"
            )

        output = "\n\n".join(formatted_results)
        logger.info("Search tool output:\n%s", output)
        return output

    except Exception:
        logger.exception("Web search failed")
        return "Web search failed."


research_agent = create_agent(
    model="ollama:llama3.1",
    tools=[web_search],
    system_prompt=(
        "You are a research specialist. "
        "Use the web_search tool to find information relevant to the user's query. "
        "Read the search result descriptions carefully and summarize the findings in clear, natural language. "
        "Mention uncertainty when the results do not provide enough information."
    ),
)


@tool("research", description="Research a topic using web search and summarize the findings")
def call_research_agent(query: str) -> str:
    """Delegate research tasks to the research subagent."""
    logger.info("Delegating research query to subagent: %s", query)

    try:
        result = research_agent.invoke({"messages": [{"role": "user", "content": query}]})
        answer = result["messages"][-1].content
        logger.info("Research subagent completed successfully")
        return answer
    except Exception:
        logger.exception("Research subagent failed")
        return "The research subagent could not complete the request."