"""Release-pinned content cache and request-scoped inference runtime."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import sqlalchemy as sa

from apps.api.security import SecretBox
from database.models.platform import (
    ContentReleaseORM,
    LlmCredentialORM,
    PlaythroughORM,
    UsageLedgerORM,
    UserORM,
)
from database.repositories.sql import SqlUnitOfWork
from engine.contentpack.legacy_v2 import trusted_plugin_tree_checksum
from engine.contentpack.pack import ContentPack
from engine.contentpack.plugin_loader import load_rule_plugin
from engine.contentpack.runtime_v2 import content_pack_from_v2
from engine.contentpack.schema_v2 import ContentPackageV2
from engine.core.config import Settings
from engine.core.errors import ConcurrencyError
from engine.core.ids import new_id
from engine.core.locks import InMemoryLockBackend, LockBackend
from engine.core.logging import get_logger
from engine.llm.budget import BudgetedProvider
from engine.llm.providers import build_provider
from engine.orchestrator.factory import build_orchestrator
from engine.orchestrator.orchestrator import GameOrchestrator


class InferenceQuotaExceeded(RuntimeError):
    pass


class RuntimeConfigurationError(RuntimeError):
    pass


logger = get_logger("runtime")


def llm_cost_microunits(
    settings: Settings,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> int:
    price = (
        settings.llm_price_table.get(f"{provider}:{model}")
        or settings.llm_price_table.get(f"{provider}:*")
        or settings.llm_price_table.get("default")
        or {}
    )
    return (
        input_tokens * int(price.get("input_per_million", 0))
        + output_tokens * int(price.get("output_per_million", 0))
    ) // 1_000_000


def _byok_runtime_settings(
    settings: Settings, *, provider: str, secret: str, model: str, base_url: str = ""
) -> Settings:
    """Build an isolated model configuration for one player's credential."""
    return settings.model_copy(
        update={
            "llm_provider": provider,
            "llm_api_key": secret,
            "llm_api_keys": "",
            "llm_base_url": base_url,
            "llm_model": model,
            # Platform role overrides must never leak into a BYOK runtime;
            # every text role uses the model the player chose.
            "intent_model": "",
            "npc_model": "",
            "npc_major_model": "",
            "director_model": "",
            "steward_model": "",
            "narrative_model": "",
            "memory_model": "",
            "embedding_model": "",
        }
    )


class RedisLockBackend:
    """Infrastructure adapter for a cross-process world lock."""

    def __init__(self, redis_url: str, *, timeout_seconds: float = 30.0) -> None:
        from redis.asyncio import from_url

        self._redis = from_url(redis_url, decode_responses=True)
        self._timeout = timeout_seconds

    @asynccontextmanager
    async def acquire(self, key: str, ttl_seconds: float = 120.0) -> AsyncIterator[None]:
        lock = self._redis.lock(
            f"narrative:lock:{key}",
            timeout=ttl_seconds,
            blocking_timeout=self._timeout,
        )
        if not await lock.acquire():
            raise ConcurrencyError(f"could not acquire lock {key}", key=key)
        try:
            yield
        finally:
            try:
                await lock.release()
            except Exception as exc:
                if exc.__class__.__name__ != "LockNotOwnedError":
                    raise

    async def close(self) -> None:
        await self._redis.aclose()


@dataclass(slots=True)
class ReleaseRuntime:
    release_id: str
    checksum: str
    pack: ContentPack
    orchestrator: GameOrchestrator
    credential_mode: Literal["platform", "byok"]
    settings: Settings


class ReleaseContentCache:
    """Caches immutable content only; mutable LLM traces never cross requests."""

    def __init__(self, max_entries: int = 32) -> None:
        self._entries: OrderedDict[str, ContentPack] = OrderedDict()
        self.max_entries = max_entries

    def resolve(self, release: ContentReleaseORM, settings: Settings) -> ContentPack:
        cached = self._entries.get(release.checksum)
        if cached:
            self._entries.move_to_end(release.checksum)
            return cached
        package = ContentPackageV2.model_validate(
            {"manifest": release.artifact["manifest"], "content": release.artifact["content"]}
        )
        pack = content_pack_from_v2(package, content_dir=settings.content_path)
        if package.manifest.trusted_rule_plugin:
            self._install_trusted_plugin(pack, package, release, settings)
        self._entries[release.checksum] = pack
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)
        return pack

    @staticmethod
    def _install_trusted_plugin(
        pack: ContentPack,
        package: ContentPackageV2,
        release: ContentReleaseORM,
        settings: Settings,
    ) -> None:
        from database.bootstrap import SYSTEM_USER_ID

        if release.owner_id != SYSTEM_USER_ID:
            raise RuntimeConfigurationError("untrusted release requested a Python rule plugin")
        root = (settings.content_path / package.manifest.key).resolve()
        expected = str(package.content.world.get("trusted_rule_plugin_sha256", ""))
        if not expected or not root.is_dir() or trusted_plugin_tree_checksum(root) != expected:
            raise RuntimeConfigurationError("installed trusted rule plugin does not match Release")
        declaration = package.content.world.get("trusted_rule_plugin")
        if not isinstance(declaration, dict):
            raise RuntimeConfigurationError("trusted rule plugin declaration is incomplete")
        pack.root = root
        pack.meta["rule_plugin"] = declaration
        pack.rule_plugin = load_rule_plugin(root, pack.meta)


class RuntimeInfrastructure:
    def __init__(self) -> None:
        self._memory_lock = InMemoryLockBackend()
        self._redis_locks: dict[str, RedisLockBackend] = {}

    def lock_backend(self, settings: Settings) -> LockBackend:
        if not settings.redis_url:
            return self._memory_lock
        backend = self._redis_locks.get(settings.redis_url)
        if backend is None:
            backend = RedisLockBackend(settings.redis_url)
            self._redis_locks[settings.redis_url] = backend
        return backend


class ReleaseRuntimeService:
    def __init__(self, content: ReleaseContentCache, infrastructure: RuntimeInfrastructure) -> None:
        self.content = content
        self.infrastructure = infrastructure

    async def resolve(
        self,
        release: ContentReleaseORM,
        playthrough: PlaythroughORM,
        user_id: str,
        uow: SqlUnitOfWork,
        settings: Settings,
    ) -> ReleaseRuntime:
        pack = self.content.resolve(release, settings)
        mode = str((playthrough.player_config or {}).get("model_mode", "platform"))
        runtime_settings = settings
        if mode == "byok":
            provider_name = str((playthrough.player_config or {}).get("provider", ""))
            credential = await uow.session.scalar(
                sa.select(LlmCredentialORM).where(
                    LlmCredentialORM.user_id == user_id,
                    LlmCredentialORM.provider == provider_name,
                    LlmCredentialORM.status == "active",
                )
            )
            if credential is None:
                raise RuntimeConfigurationError("selected BYOK credential is unavailable")
            try:
                secret = SecretBox(settings.credential_encryption_key).decrypt(
                    credential.encrypted_secret
                )
            except ValueError as exc:
                raise RuntimeConfigurationError("BYOK credential cannot be decrypted") from exc
            runtime_settings = _byok_runtime_settings(
                settings,
                provider=credential.provider,
                secret=secret,
                model=credential.default_model,
                base_url=credential.base_url,
            )
            credential_mode: Literal["platform", "byok"] = "byok"
            available = settings.llm_turn_token_limit
        else:
            credential_mode = "platform"
            available = await self._platform_tokens_available(user_id, uow, settings)
            if available <= 0:
                raise InferenceQuotaExceeded("platform inference quota exhausted")

        provider = BudgetedProvider(
            build_provider(runtime_settings), min(settings.llm_turn_token_limit, available)
        )
        orchestrator = build_orchestrator(
            settings=runtime_settings,
            pack=pack,
            provider=provider,
            lock_backend=self.infrastructure.lock_backend(settings),
        )
        return ReleaseRuntime(
            release_id=release.id,
            checksum=release.checksum,
            pack=pack,
            orchestrator=orchestrator,
            credential_mode=credential_mode,
            settings=settings,
        )

    async def _platform_tokens_available(
        self, user_id: str, uow: SqlUnitOfWork, settings: Settings
    ) -> int:
        now = datetime.now(UTC)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = day_start.replace(day=1)
        token_sum = sa.func.coalesce(
            sa.func.sum(UsageLedgerORM.input_tokens + UsageLedgerORM.output_tokens), 0
        )
        daily = int(
            await uow.session.scalar(
                sa.select(token_sum).where(
                    UsageLedgerORM.user_id == user_id,
                    UsageLedgerORM.created_at >= day_start,
                    UsageLedgerORM.provider != "byok",
                )
            )
            or 0
        )
        monthly = int(
            await uow.session.scalar(
                sa.select(token_sum).where(
                    UsageLedgerORM.user_id == user_id,
                    UsageLedgerORM.created_at >= month_start,
                    UsageLedgerORM.provider != "byok",
                )
            )
            or 0
        )
        user = await uow.session.get(UserORM, user_id)
        user_monthly = user.platform_quota_monthly if user else settings.llm_monthly_token_limit
        monthly_limit = min(settings.llm_monthly_token_limit, user_monthly)
        return min(settings.llm_daily_token_limit - daily, monthly_limit - monthly)

    async def record_usage(
        self,
        runtime: ReleaseRuntime,
        user_id: str,
        playthrough_id: str,
        uow: SqlUnitOfWork,
    ) -> None:
        llm = runtime.orchestrator.d.llm
        records = list(llm.records) if llm is not None else []
        now = datetime.now(UTC)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        prior_cost = int(
            await uow.session.scalar(
                sa.select(sa.func.coalesce(sa.func.sum(UsageLedgerORM.cost_microunits), 0)).where(
                    UsageLedgerORM.created_at >= day_start,
                    UsageLedgerORM.provider != "byok",
                )
            )
            or 0
        )
        added_cost = 0
        for record in records:
            cost = 0
            if runtime.credential_mode != "byok":
                cost = llm_cost_microunits(
                    runtime.settings,
                    record.provider,
                    record.model,
                    record.prompt_tokens,
                    record.completion_tokens,
                )
            added_cost += cost
            uow.session.add(
                UsageLedgerORM(
                    id=new_id(),
                    user_id=user_id,
                    playthrough_id=playthrough_id,
                    provider="byok" if runtime.credential_mode == "byok" else record.provider,
                    model=record.model,
                    input_tokens=record.prompt_tokens,
                    output_tokens=record.completion_tokens,
                    cost_microunits=cost,
                    success=record.valid and not record.degraded,
                )
            )
        if records:
            await uow.commit()
            threshold = runtime.settings.llm_daily_cost_alert_microunits
            if threshold and prior_cost < threshold <= prior_cost + added_cost:
                logger.warning(
                    "daily LLM cost threshold crossed cost_microunits=%s threshold=%s",
                    prior_cost + added_cost,
                    threshold,
                )


release_content_cache = ReleaseContentCache()
release_runtime_service = ReleaseRuntimeService(release_content_cache, RuntimeInfrastructure())
