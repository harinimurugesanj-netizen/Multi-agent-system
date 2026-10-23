from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    database_url: str
    llm_model: str
    llm_base_url: str
    log_level: str
    studio_customer_id: str
    currency_symbol: str
    max_clarifications: int

@lru_cache
def get_settings() -> Settings:
    return Settings()