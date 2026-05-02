"""Configuration loaded from .env"""
from pathlib import Path
import os
import tempfile

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

    # Runtime data directory. Vercel functions can only write safely to /tmp.
    runtime_data_dir: str = ""


settings = Settings()


def get_runtime_data_dir() -> Path:
    if settings.runtime_data_dir:
        data_dir = Path(settings.runtime_data_dir)
    elif os.getenv("VERCEL"):
        data_dir = Path(tempfile.gettempdir()) / "buffett-bot-data"
    else:
        data_dir = Path(__file__).resolve().parent / "data"

    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir
