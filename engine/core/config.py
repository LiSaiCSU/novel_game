"""Runtime configuration. Everything comes from the environment / .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "dev"
    debug_mode: bool = True
    log_level: str = "INFO"
    log_json: bool = False

    database_url: str = "sqlite+aiosqlite:///./data/game.db"
    database_echo: bool = False
    redis_url: str = ""

    content_pack: str = "cultivation_v1"
    content_dir: str = "./content"

    # --- LLM ---------------------------------------------------------------
    llm_provider: str = "null"
    anthropic_api_key: str = ""
    anthropic_base_url: str = ""
    openai_api_key: str = ""
    openai_base_url: str = ""
    compatible_api_key: str = ""
    compatible_base_url: str = ""

    # Model names are never hardcoded in source (Prompt section 48).
    intent_model: str = ""
    npc_model: str = ""
    npc_major_model: str = ""
    director_model: str = ""
    narrative_model: str = ""
    memory_model: str = ""
    embedding_model: str = ""

    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 1
    llm_max_repairs: int = 2

    # --- Prompt versions ---------------------------------------------------
    prompt_version_player_intent: str = "v1"
    prompt_version_npc_decision: str = "v1"
    prompt_version_director: str = "v1"
    prompt_version_narrative: str = "v1"
    prompt_version_memory_extractor: str = "v1"

    # --- Context budgets ---------------------------------------------------
    ctx_budget_intent: int = 1200
    ctx_budget_npc: int = 2500
    ctx_budget_director: int = 3000
    ctx_budget_narrative: int = 3500
    ctx_budget_memory: int = 1200

    # --- Simulation --------------------------------------------------------
    sim_max_offline_minutes: int = 525_600
    director_min_interval_turns: int = 3

    # --- Embeddings --------------------------------------------------------
    embedding_backend: str = "hash"
    embedding_dim: int = 256

    # --- API ---------------------------------------------------------------
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    cors_origins: str = "*"

    prompts_dir: str = Field(default=str(REPO_ROOT / "prompts"))

    @property
    def content_path(self) -> Path:
        p = Path(self.content_dir)
        return p if p.is_absolute() else (REPO_ROOT / p).resolve()

    @property
    def prompts_path(self) -> Path:
        p = Path(self.prompts_dir)
        return p if p.is_absolute() else (REPO_ROOT / p).resolve()

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """Test hook: force the next get_settings() call to re-read the environment."""
    get_settings.cache_clear()
