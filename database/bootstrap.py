"""Idempotent installation of bundled official projects and releases."""

from __future__ import annotations

import hashlib
import io
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import sqlalchemy as sa
from PIL import Image

import database.session as db_session
from database.models.platform import (
    AssetORM,
    AuditLogORM,
    ContentReleaseORM,
    ProjectORM,
    ProjectRevisionORM,
    UserORM,
    UserRoleORM,
)
from engine.contentpack.compiler import compile_package
from engine.contentpack.legacy_v2 import project_v1_as_v2
from engine.contentpack.pack import load_content_pack
from engine.core.config import Settings
from engine.core.ids import new_id

SYSTEM_USER_ID = "00000000-0000-0000-0000-000000000001"


class AssetStore(Protocol):
    async def put(self, key: str, payload: bytes, content_type: str) -> None: ...


def configured_super_admin_emails(settings: Settings) -> frozenset[str]:
    """Return an intentionally deployment-owned list of bootstrap accounts."""

    return frozenset(
        item.strip().casefold()
        for item in settings.super_admin_emails.replace("\n", ",").split(",")
        if item.strip()
    )


async def ensure_configured_super_admins(settings: Settings) -> int:
    """Grant the break-glass role only to verified, server-configured users.

    This solves the initial-admin problem without giving an ordinary database
    administrator a browser-accessible way to bootstrap the highest role.
    Removing an address from the environment does *not* silently demote an
    account; demotion remains a deliberate, audited super-admin operation.
    """

    emails = configured_super_admin_emails(settings)
    if not emails:
        return 0
    maker = db_session.get_sessionmaker(settings)
    async with maker() as session:
        users = (
            await session.scalars(
                sa.select(UserORM).where(
                    UserORM.email.in_(emails),
                    UserORM.email_verified_at.is_not(None),
                    UserORM.status == "active",
                )
            )
        ).all()
        promoted = 0
        for user in users:
            existing = set(
                (
                    await session.scalars(
                        sa.select(UserRoleORM.role).where(UserRoleORM.user_id == user.id)
                    )
                ).all()
            )
            added = {"admin", "super_admin"} - existing
            if not added:
                continue
            session.add_all(UserRoleORM(id=new_id(), user_id=user.id, role=role) for role in added)
            session.add(
                AuditLogORM(
                    id=new_id(),
                    actor_id=None,
                    action="system.super_admin_bootstrapped",
                    target_type="user",
                    target_id=user.id,
                    request_id="bootstrap",
                    details={"roles_added": sorted(added), "source": "SUPER_ADMIN_EMAILS"},
                )
            )
            promoted += 1
        if promoted:
            await session.commit()
        return promoted


@lru_cache(maxsize=32)
def _prepared_official_asset(
    source_name: str, modified_ns: int, content_type: str
) -> tuple[bytes, int, int]:
    del modified_ns  # Part of the cache key so replaced files are reprocessed.
    with Image.open(source_name) as original:
        width, height = original.size
        cleaned = original.convert("RGB")
        output = io.BytesIO()
        suffix = Path(source_name).suffix.casefold()
        output_format = "JPEG" if content_type == "image/jpeg" else suffix[1:].upper()
        cleaned.save(output, format=output_format, quality=90, optimize=True)
    return output.getvalue(), width, height


async def ensure_official_releases(
    settings: Settings, asset_store: AssetStore | None = None
) -> None:
    if asset_store is None:
        # Keep CLI, migration verification and older operational callers
        # compatible while the API lifespan continues to inject this adapter.
        from apps.api.object_store import object_store

        asset_store = object_store(settings)
    maker = db_session.get_sessionmaker(settings)
    async with maker() as session:
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            await session.execute(
                sa.text("SELECT set_config('app.current_user_id', :user_id, true)"),
                {"user_id": SYSTEM_USER_ID},
            )
        system = await session.get(UserORM, SYSTEM_USER_ID)
        if system is None:
            system = UserORM(
                id=SYSTEM_USER_ID,
                email="official@local.invalid",
                password_hash="!system-account-no-login!",
                display_name="官方内容团队",
                status="system",
                email_verified_at=None,
            )
            session.add(system)
            await session.flush()
            session.add(UserRoleORM(id=new_id(), user_id=system.id, role="admin"))
            await session.flush()
        await _ensure_pack(
            session, settings, asset_store, "cultivation_v1", "seven-day-blood-pact",
            ["修仙", "悬疑"],
        )
        campus_dir = settings.content_path / "campus_romance_v1"
        if campus_dir.is_dir():
            await _ensure_pack(
                session, settings, asset_store, "campus_romance_v1",
                "unfinished-spring-messages", ["校园", "恋爱", "女性向"],
            )
        tomb_dir = settings.content_path / "tomb_lantern_v1"
        if tomb_dir.is_dir():
            await _ensure_pack(
                session, settings, asset_store, "tomb_lantern_v1",
                "nine-branch-lantern", ["盗墓", "悬疑", "冒险", "民国"],
            )
        fog_dir = settings.content_path / "fog_harbor_v1"
        if fog_dir.is_dir():
            await _ensure_pack(
                session, settings, asset_store, "fog_harbor_v1",
                "egret-in-the-fog", ["剧本杀", "推理", "悬疑", "暴风雪山庄"],
            )
        spirit_pact_dir = settings.content_path / "spirit_pact_v1"
        if spirit_pact_dir.is_dir():
            await _ensure_pack(
                session, settings, asset_store, "spirit_pact_v1",
                "nine-sigil-choices", ["东方玄幻", "学院", "成长", "冒险"],
            )
        three_year_dir = settings.content_path / "three_year_pact_v1"
        if three_year_dir.is_dir():
            await _ensure_pack(
                session, settings, asset_store, "three_year_pact_v1",
                "three-year-pact", ["都市", "逆袭", "打脸", "短剧"],
            )
        second_chance_dir = settings.content_path / "second_chance_v1"
        if second_chance_dir.is_dir():
            await _ensure_pack(
                session, settings, asset_store, "second_chance_v1",
                "second-chance", ["重生", "年代", "复仇", "短剧"],
            )
        wedding_verdict_dir = settings.content_path / "wedding_verdict_v1"
        if wedding_verdict_dir.is_dir():
            await _ensure_pack(
                session, settings, asset_store, "wedding_verdict_v1",
                "wedding-verdict", ["都市", "复仇", "商战", "短剧"],
            )
        divorce_ledger_dir = settings.content_path / "divorce_ledger_v1"
        if divorce_ledger_dir.is_dir():
            await _ensure_pack(
                session, settings, asset_store, "divorce_ledger_v1",
                "divorce-ledger", ["古装", "和离", "查案", "短剧"],
            )
        shelter_broadcast_dir = settings.content_path / "shelter_broadcast_v1"
        if shelter_broadcast_dir.is_dir():
            await _ensure_pack(
                session, settings, asset_store, "shelter_broadcast_v1",
                "shelter-broadcast", ["末日", "科幻", "生存", "短剧"],
            )
        for pack_key, slug, tags in (
            ("seoul_blackout_v1", "seoul-blackout", ["韩式", "逃杀", "密室", "悬疑"]),
            ("zombie_station_v1", "last-train-terminal", ["丧尸", "末日", "地铁", "生存"]),
            ("war_radio_v1", "frontline-radio", ["战争", "电台", "群像", "抉择"]),
            ("exiled_empress_v1", "exiled-empress", ["穿越", "古装", "权谋", "逆袭"]),
            ("jade_gate_expedition_v1", "jade-gate-expedition", ["地宫", "探险", "机关", "悬疑"]),
            ("room_404_v1", "room-404", ["灵异", "酒店", "推理", "惊悚"]),
            ("jiangshi_courier_v1", "jiangshi-courier", ["僵尸", "民俗", "喜剧", "冒险"]),
            ("heartbeat_countdown_v1", "heartbeat-countdown", ["恋爱", "轻喜剧", "职场", "都市"]),
            ("abyss_oxygen_v1", "abyss-oxygen", ["灾难", "科幻", "深海", "生存"]),
            ("live_court_v1", "live-court", ["庭审", "直播", "反转", "悬疑"]),
        ):
            if (settings.content_path / pack_key).is_dir():
                await _ensure_pack(session, settings, asset_store, pack_key, slug, tags)
        await session.commit()


async def _ensure_pack(
    session,
    settings: Settings,
    asset_store: AssetStore,
    pack_key: str,
    slug: str,
    tags: list[str],
) -> None:
    pack = load_content_pack(settings.content_path, pack_key)
    package = project_v1_as_v2(pack, slug=slug, rating="16+", tags=tags)
    compiled = compile_package(package)
    project = await session.scalar(
        sa.select(ProjectORM).where(
            ProjectORM.owner_id == SYSTEM_USER_ID, ProjectORM.slug == slug
        )
    )
    if project is None:
        project = ProjectORM(
            id=new_id(), owner_id=SYSTEM_USER_ID, slug=slug, title=package.manifest.title,
            summary=package.manifest.summary, locale=package.manifest.locale,
            rating=package.manifest.rating, status="published", current_revision=0,
            project_metadata={"official": True},
        )
        session.add(project)
        await session.flush()
    await _ensure_official_assets(session, asset_store, project, pack, package.manifest.assets)
    existing = await session.scalar(
        sa.select(ContentReleaseORM).where(
            ContentReleaseORM.project_id == project.id,
            ContentReleaseORM.checksum == compiled.checksum,
        )
    )
    if existing is not None:
        return
    version_collision = await session.scalar(
        sa.select(ContentReleaseORM.id).where(
            ContentReleaseORM.project_id == project.id,
            ContentReleaseORM.version == package.manifest.version,
        )
    )
    if version_collision:
        raise RuntimeError(
            f"official pack {pack_key!r} changed without a version bump ({package.manifest.version})"
        )
    project.current_revision += 1
    project.title = package.manifest.title
    project.summary = package.manifest.summary
    project.locale = package.manifest.locale
    project.rating = package.manifest.rating
    revision = ProjectRevisionORM(
        id=new_id(), project_id=project.id, author_id=SYSTEM_USER_ID,
        revision=project.current_revision,
        document=package.model_dump(mode="json"), diagnostics=[]
    )
    # Keep this ordering explicit. PostgreSQL enforces the release -> revision
    # foreign key during flush; relying on a later add_all() left ordering to
    # the ORM and failed on a truly empty production-shaped database.
    session.add(revision)
    await session.flush()
    release = ContentReleaseORM(
        id=new_id(), project_id=project.id, revision_id=revision.id, owner_id=SYSTEM_USER_ID,
        version=package.manifest.version, checksum=compiled.checksum, title=package.manifest.title,
        summary=package.manifest.summary, locale=package.manifest.locale, rating=package.manifest.rating,
        tags=package.manifest.tags, visibility="public", moderation_status="approved",
        artifact=compiled.model_dump(mode="json"),
        published_at=datetime.now(UTC),
    )
    await session.execute(
        sa.update(ContentReleaseORM)
        .where(
            ContentReleaseORM.project_id == project.id,
            ContentReleaseORM.visibility == "public",
            ContentReleaseORM.withdrawn_at.is_(None),
        )
        .values(withdrawn_at=sa.func.now())
    )
    session.add(release)


async def _ensure_official_assets(
    session,
    asset_store: AssetStore,
    project: ProjectORM,
    pack,
    assets,
) -> None:
    """Install bundled media through the same private object-store path as creator uploads."""
    content_types = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
    for asset in assets:
        source = pack.root / "assets" / Path(asset.path).name
        content_type = content_types.get(source.suffix.casefold())
        if not content_type or not source.is_file():
            raise RuntimeError(f"official asset source is missing or unsupported: {source}")
        payload, width, height = _prepared_official_asset(
            str(source), source.stat().st_mtime_ns, content_type
        )
        checksum = hashlib.sha256(payload).hexdigest()
        await asset_store.put(asset.path, payload, content_type)
        row = await session.scalar(
            sa.select(AssetORM).where(
                AssetORM.project_id == project.id,
                AssetORM.logical_key == asset.key,
            )
        )
        if row is None:
            row = AssetORM(
                id=new_id(), owner_id=SYSTEM_USER_ID, project_id=project.id,
                logical_key=asset.key, kind=asset.kind, object_key=asset.path,
                content_type=content_type, byte_size=len(payload), checksum=checksum,
                width=width, height=height, alt_text=asset.alt, status="ready",
            )
            session.add(row)
        else:
            row.kind = asset.kind
            row.object_key = asset.path
            row.content_type = content_type
            row.byte_size = len(payload)
            row.checksum = checksum
            row.width = width
            row.height = height
            row.alt_text = asset.alt
            row.status = "ready"
