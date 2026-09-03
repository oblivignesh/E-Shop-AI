"""Centralized settings loaded from environment / .env."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    router_model: str = Field(default="claude-haiku-4-5", alias="AURA_ROUTER_MODEL")
    agent_model: str = Field(default="claude-sonnet-4-5", alias="AURA_AGENT_MODEL")

    # Observability
    langsmith_tracing: bool = Field(default=False, alias="LANGSMITH_TRACING")
    langsmith_api_key: str = Field(default="", alias="LANGSMITH_API_KEY")
    langsmith_project: str = Field(default="aura-eshop", alias="LANGSMITH_PROJECT")

    # Paths (relative to repo root)
    db_path: Path = Field(default=Path("data/aura.db"), alias="AURA_DB_PATH")
    checkpoint_db_path: Path = Field(
        default=Path("data/checkpoints.db"), alias="AURA_CHECKPOINT_DB_PATH"
    )
    chroma_dir: Path = Field(default=Path("data/chroma"), alias="AURA_CHROMA_DIR")
    policies_dir: Path = Field(default=Path("policies"), alias="AURA_POLICIES_DIR")
    raw_data_dir: Path = Field(default=Path("data/raw"), alias="AURA_RAW_DATA_DIR")

    # Business rules
    refund_auto_approve_max: float = Field(
        default=5000.0, alias="AURA_REFUND_AUTO_APPROVE_MAX"
    )
    currency_symbol: str = Field(default="₹", alias="AURA_CURRENCY_SYMBOL")
    currency_code: str = Field(default="INR", alias="AURA_CURRENCY_CODE")

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path.as_posix()}"


settings = Settings()
