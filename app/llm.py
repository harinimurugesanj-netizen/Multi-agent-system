"""Qwen3 clients (served locally by Ollama): one strict-JSON, one conversational."""
from langchain_ollama import ChatOllama

from config.config import get_settings


def get_json_llm() -> ChatOllama:
    s = get_settings()
    return ChatOllama(model=s.llm_model, base_url=s.llm_base_url, temperature=0, format="json")


def get_chat_llm() -> ChatOllama:
    s = get_settings()
    return ChatOllama(model=s.llm_model, base_url=s.llm_base_url, temperature=0.2)
