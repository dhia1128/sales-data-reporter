from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """App settings. Every field can be overridden by an env var or a .env file."""

    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    app_name: str = "Data Report Analyzer"
    debug: bool = False

    database_url: str = f"sqlite:///{BASE_DIR / 'data' / 'app.db'}"
    upload_dir: Path = BASE_DIR / "data" / "uploads"
    max_upload_mb: int = 20

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:latest"
    llm_timeout: int = 120

    report_language: str = "French"
    top_n: int = 5
    # How to read ambiguous dates like 05/03/2024 (True = 5 March)
    date_dayfirst: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
