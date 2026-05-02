"""Configuration loaded from .env"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # DART OpenAPI
    dart_api_key: str = ""

    # 분석/백테스트 파라미터
    margin_of_safety: float = 0.25
    split_buy_count: int = 3


settings = Settings()
