"""Configuration for Guardrails service."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Server
    guardrails_port: int = 8200

    # Upstream LLM (Gemma manager)
    upstream_llm_base_url: str = "http://127.0.0.1:9000/v1"
    upstream_llm_model: str = "gemma-4-31b"
    upstream_llm_api_key: str = "sk-local-dev"

    # Timeouts
    upstream_connect_timeout: float = 10.0
    upstream_read_timeout: float = 120.0

    # Policy
    policy_version: str = "mvp-1"

    # NeMo Guardrails config path
    nemo_config_path: str = "config"

    @property
    def upstream_chat_url(self) -> str:
        """Full URL for chat completions endpoint."""
        return f"{self.upstream_llm_base_url.rstrip('/')}/chat/completions"

    @property
    def upstream_health_url(self) -> str:
        """Manager health endpoint (root-level, not under /v1)."""
        base = self.upstream_llm_base_url.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        return f"{base}/health"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


def load_nemo_config(config_path: Optional[str] = None) -> dict:
    """Load NeMo Guardrails configuration from YAML and Colang files."""
    import yaml

    settings = get_settings()
    path = Path(config_path or settings.nemo_config_path)

    # Load config.yml
    config_file = path / "config.yml"
    if not config_file.exists():
        raise FileNotFoundError(f"NeMo config not found at {config_file}")

    with config_file.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Load rails.co
    rails_file = path / "rails.co"
    if rails_file.exists():
        with rails_file.open("r", encoding="utf-8") as f:
            config["rails_colang"] = f.read()

    return config