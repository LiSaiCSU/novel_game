"""Runtime configuration. Everything comes from the environment / .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
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
    metrics_token: str = ""
    sentry_dsn: str = ""
    sentry_traces_sample_rate: float = Field(default=0.1, ge=0, le=1)
    slow_query_seconds: float = Field(default=0.3, ge=0.01, le=60)

    database_url: str = "sqlite+aiosqlite:///./data/game.db"
    database_echo: bool = False
    redis_url: str = ""

    content_pack: str = "cultivation_v1"
    content_dir: str = "./content"

    # --- LLM ---------------------------------------------------------------
    llm_provider: str = "null"
    # Unified configuration for the common case.  One model can serve every
    # text role, while the role-specific fields below remain optional
    # overrides.  LLM_API_KEYS accepts comma/newline separated keys and is
    # used as a round-robin pool for concurrent requests.
    llm_api_key: str = ""
    llm_api_keys: str = ""
    llm_base_url: str = ""
    llm_model: str = ""
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
    steward_model: str = ""
    narrative_model: str = ""
    memory_model: str = ""
    embedding_model: str = ""

    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 1
    llm_max_repairs: int = 2
    #: JSON merged verbatim into every request body. Vendor switches such as a
    #: thinking-mode toggle live here so no vendor name enters engine code.
    #: The legacy/global value is also the narrative profile value.
    llm_extra_body: str = ""
    #: Optional request-body switches for structured reasoning roles. Blank
    #: inherits ``llm_extra_body`` so old single-model deployments are unchanged.
    llm_reasoning_extra_body: str = ""
    #: Multiplier applied to every role's output budget. Reasoning models bill
    #: hidden thought against the same budget, so they need a bigger one.
    llm_output_budget_scale: float = 1.0
    #: How many times a truncated (empty) response is retried with twice the
    #: budget before the caller is allowed to degrade.
    llm_truncation_retries: int = 2
    # One turn is not one model call: it is intent, world steward, two NPC
    # agents, the director, memory, and a chapter of prose, each with a
    # multi-thousand-token prompt. The old 20k default was smaller than a
    # healthy turn, so any deployment that did not override it lost its
    # chapter - the part the player reads - to the budget guard every turn.
    # These match the documented values in .env.example.
    llm_turn_token_limit: int = Field(default=120_000, ge=1)
    llm_daily_token_limit: int = Field(default=2_000_000, ge=1)
    llm_monthly_token_limit: int = Field(default=100_000_000, ge=1)
    llm_price_table: dict[str, dict[str, int]] = Field(default_factory=dict)
    llm_daily_cost_alert_microunits: int = Field(default=0, ge=0)

    # --- Prompt versions ---------------------------------------------------
    prompt_version_player_intent: str = "v1"
    prompt_version_npc_decision: str = "v1"
    prompt_version_director: str = "v1"
    prompt_version_world_steward: str = "v1"
    prompt_version_plot_steward: str = "v1"
    prompt_version_autopilot: str = "v1"
    prompt_version_prologue: str = "v1"
    prompt_version_chapter: str = "v1"
    prompt_version_narrative: str = "v1"
    prompt_version_memory_extractor: str = "v1"

    # --- Context budgets ---------------------------------------------------
    ctx_budget_intent: int = 2600
    ctx_budget_npc: int = 2500
    ctx_budget_director: int = 3000
    ctx_budget_narrative: int = 7000
    ctx_budget_memory: int = 1200

    # --- Simulation --------------------------------------------------------
    # 0 delegates the maximum duration to the active content pack.  A positive
    # value is a deployment safety limit and is rejected, never silently clipped.
    sim_max_offline_minutes: int = 0
    director_min_interval_turns: int = 3

    # --- Embeddings --------------------------------------------------------
    embedding_backend: str = "hash"
    embedding_dim: int = 256

    # --- API ---------------------------------------------------------------
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    cors_origins: str = "*"

    # --- Identity and public application ---------------------------------
    public_app_url: str = "http://127.0.0.1:3000"
    auth_cookie_name: str = "ng_session"
    csrf_cookie_name: str = "ng_csrf"
    auth_cookie_secure: bool = False
    auth_session_days: int = 30
    email_token_minutes: int = 30
    # Verification codes are short enough to type from a phone, so they get a
    # tighter window and a hard per-code guess budget instead of link lifetime.
    email_code_minutes: int = Field(default=15, ge=1, le=120)
    email_code_max_attempts: int = Field(default=5, ge=1, le=20)
    auth_pepper: str = "change-me-in-production"
    credential_encryption_key: str = ""
    require_verified_email: bool = True
    admin_mfa_required: bool = True
    mfa_step_up_minutes: int = Field(default=720, ge=5, le=1440)
    adult_catalog_enabled: bool = False
    assets_dir: str = "./data/assets"
    object_store_backend: str = "local"
    s3_endpoint_url: str = ""
    s3_bucket: str = "narrative-assets"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "us-east-1"
    clamav_host: str = ""
    clamav_port: int = Field(default=3310, ge=1, le=65535)
    clamav_timeout_seconds: float = Field(default=20.0, ge=1, le=120)

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = "noreply@example.invalid"
    smtp_ssl: bool = False
    smtp_starttls: bool = True

    prompts_dir: str = Field(default=str(REPO_ROOT / "prompts"))

    @model_validator(mode="after")
    def reject_unsafe_production_configuration(self) -> Settings:
        if self.app_env.lower() not in {"prod", "production"}:
            return self
        problems: list[str] = []
        if self.debug_mode:
            problems.append("DEBUG_MODE must be false")
        if not self.database_url.startswith("postgresql"):
            problems.append("DATABASE_URL must use PostgreSQL")
        if not self.redis_url:
            problems.append("REDIS_URL is required")
        if not self.auth_cookie_secure:
            problems.append("AUTH_COOKIE_SECURE must be true")
        if len(self.auth_pepper) < 32 or self.auth_pepper == "change-me-in-production":
            problems.append("AUTH_PEPPER must be a strong injected secret")
        if len(self.credential_encryption_key) < 32:
            problems.append("CREDENTIAL_ENCRYPTION_KEY must be a strong injected secret")
        if not self.cors_origin_list or "*" in self.cors_origin_list:
            problems.append("CORS_ORIGINS must be explicit")
        if not self.public_app_url.startswith("https://"):
            problems.append("PUBLIC_APP_URL must use HTTPS")
        if self.object_store_backend != "s3":
            problems.append("OBJECT_STORE_BACKEND must be s3")
        if not self.clamav_host:
            problems.append("CLAMAV_HOST is required")
        if not self.require_verified_email:
            problems.append("REQUIRE_VERIFIED_EMAIL must be true")
        if len(self.metrics_token) < 24:
            problems.append("METRICS_TOKEN must be a strong injected secret")
        if not self.sentry_dsn:
            problems.append("SENTRY_DSN is required")
        if problems:
            raise ValueError("unsafe production configuration: " + "; ".join(problems))
        return self

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
