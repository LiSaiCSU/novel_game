"""Idempotent background jobs.

Each task owns its transaction and can safely be retried.  Tenant-scoped jobs
receive the owner id and set the same PostgreSQL RLS context as an API request.
Global retention jobs discover due accounts from the identity table, then set
the due account as transaction tenant before touching any RLS-protected rows.
"""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from PIL import Image

import database.session as db_session
from apps.api.emailer import deliver_email
from apps.api.object_store import object_store
from apps.api.tenancy import set_tenant_context
from database.models.orm import NarrativeSegmentORM, SaveSlotORM, TurnORM
from database.models.platform import (
    AssetORM,
    AuditLogORM,
    AuthSessionORM,
    ContentReleaseORM,
    DataExportORM,
    EmailTokenORM,
    LlmCredentialORM,
    ModerationCaseORM,
    PlaythroughORM,
    ProductEventORM,
    ProjectORM,
    ProjectRevisionORM,
    ReportORM,
    SupportCaseMessageORM,
    SupportCaseORM,
    UsageLedgerORM,
    UserNotificationORM,
    UserORM,
    UserRoleORM,
)
from engine.contentpack.compiler import compile_package, validate_package_graph
from engine.contentpack.schema_v2 import ContentPackageV2
from engine.core.config import Settings
from engine.core.ids import new_id


async def cleanup_expired_previews(settings: Settings) -> int:
    maker = db_session.get_sessionmaker(settings)
    async with maker() as session:
        result = await session.execute(
            sa.update(PlaythroughORM)
            .where(
                PlaythroughORM.is_preview.is_(True),
                PlaythroughORM.status == "active",
                PlaythroughORM.expires_at < datetime.now(UTC),
            )
            .values(status="expired")
        )
        await session.commit()
        return int(result.rowcount or 0)  # type: ignore[attr-defined]


async def generate_asset_thumbnail(settings: Settings, asset_id: str, owner_id: str) -> str | None:
    maker = db_session.get_sessionmaker(settings)
    async with maker() as session:
        await set_tenant_context(session, owner_id)
        asset = await session.scalar(
            sa.select(AssetORM).where(AssetORM.id == asset_id, AssetORM.owner_id == owner_id)
        )
        if asset is None:
            return None
        if asset.thumbnail_object_key:
            return asset.thumbnail_object_key
        payload = await object_store(settings).get(asset.object_key)
        with Image.open(io.BytesIO(payload)) as source:
            thumbnail = source.convert("RGB")
            thumbnail.thumbnail((512, 512), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            thumbnail.save(output, format="WEBP", quality=84, method=6)
            width, height = thumbnail.size
        # 128 checksum bits are ample for a project-scoped derivative and keep
        # local Windows development below legacy MAX_PATH limits.
        object_key = f"{owner_id}/{asset.project_id}/{asset.checksum[:32]}.thumb.webp"
        await object_store(settings).put(object_key, output.getvalue(), "image/webp")
        asset.thumbnail_object_key = object_key
        asset.thumbnail_width = width
        asset.thumbnail_height = height
        await session.commit()
        return object_key


async def scan_release(settings: Settings, release_id: str, owner_id: str) -> int:
    """Attach deterministic compiler/graph evidence to the open moderation case."""
    maker = db_session.get_sessionmaker(settings)
    async with maker() as session:
        await set_tenant_context(session, owner_id)
        release = await session.scalar(
            sa.select(ContentReleaseORM).where(
                ContentReleaseORM.id == release_id,
                ContentReleaseORM.owner_id == owner_id,
            )
        )
        if release is None:
            return 0
        package = ContentPackageV2.model_validate(
            {
                "manifest": release.artifact.get("manifest"),
                "content": release.artifact.get("content"),
            }
        )
        compiled = compile_package(package)
        problems = validate_package_graph(package)
        if compiled.checksum != release.checksum:
            problems.append("compiled artifact checksum mismatch")
        case = await session.scalar(
            sa.select(ModerationCaseORM).where(
                ModerationCaseORM.release_id == release.id,
                ModerationCaseORM.status == "pending",
            )
        )
        if case is None:
            return 0
        evidence = [item for item in case.evidence if item.get("kind") != "automated_content_scan"]
        evidence.append(
            {
                "kind": "automated_content_scan",
                "schema_version": package.manifest.schema_version,
                "rating": package.manifest.rating,
                "problems": problems,
                "checksum_verified": compiled.checksum == release.checksum,
                "scanned_at": datetime.now(UTC).isoformat(),
            }
        )
        case.evidence = evidence
        await session.commit()
        return len(problems)


async def scrub_account(session: Any, user: UserORM, *, reason: str = "") -> None:
    """Irreversibly erase one account, keeping anonymous integrity records.

    Not a row delete. Published releases may already back other people's
    playthroughs, audit entries have to outlive the account they describe, and
    several tables reference ``users.id`` without a cascade - so the personal
    data goes and the user row stays as a pseudonym. Shared by the scheduled
    purge and by an administrator erasing an account on request, because two
    implementations of "delete everything" is one too many.
    """
    await session.execute(sa.delete(AuthSessionORM).where(AuthSessionORM.user_id == user.id))
    await session.execute(sa.delete(EmailTokenORM).where(EmailTokenORM.user_id == user.id))
    await session.execute(sa.delete(LlmCredentialORM).where(LlmCredentialORM.user_id == user.id))
    await session.execute(sa.delete(UserNotificationORM).where(UserNotificationORM.user_id == user.id))
    # Support conversations are personal correspondence, not a financial
    # ledger. Delete the case and its append-only replies with the account;
    # the generic audit action remains as non-content integrity evidence.
    await session.execute(sa.delete(SupportCaseORM).where(SupportCaseORM.user_id == user.id))
    await session.execute(sa.delete(UsageLedgerORM).where(UsageLedgerORM.user_id == user.id))
    await session.execute(
        sa.update(PlaythroughORM)
        .where(PlaythroughORM.user_id == user.id)
        .values(status="deleted", player_config={})
    )
    await session.execute(
        sa.update(ProjectORM)
        .where(ProjectORM.owner_id == user.id)
        .values(status="owner_deleted", share_token_hash=None)
    )
    await session.execute(
        sa.update(ContentReleaseORM)
        .where(ContentReleaseORM.owner_id == user.id)
        .values(
            visibility="private",
            moderation_status="withdrawn",
            withdrawn_at=datetime.now(UTC),
            share_token_hash=None,
        )
    )
    user.email = f"deleted-{user.id}@invalid.local"
    user.password_hash = "!deleted!"
    user.display_name = ""
    user.user_metadata = {}
    user.platform_quota_monthly = 0
    user.status = "deleted"
    user.delete_after = None
    session.add(
        AuditLogORM(
            id=new_id(),
            actor_id=None,
            action="account.deleted",
            target_type="user",
            target_id=user.id,
            details={"retained": "pseudonymous integrity records", "reason": reason},
        )
    )


async def purge_due_accounts(settings: Settings) -> int:
    """Scrub every account whose deletion grace period has expired."""
    maker = db_session.get_sessionmaker(settings)
    async with maker() as session:
        users = (
            (
                await session.execute(
                    sa.select(UserORM).where(
                        UserORM.status == "deletion_pending",
                        UserORM.delete_after <= datetime.now(UTC),
                    )
                )
            )
            .scalars()
            .all()
        )
        for user in users:
            await set_tenant_context(session, user.id)
            await scrub_account(session, user)
        await session.commit()
        return len(users)


async def run_email(settings: Settings, payload: dict[str, object]) -> None:
    await deliver_email(
        settings,
        str(payload.get("to", "")),
        str(payload.get("subject", "")),
        str(payload.get("text", "")),
    )


async def build_data_export(settings: Settings, export_id: str, user_id: str) -> str | None:
    maker = db_session.get_sessionmaker(settings)
    try:
        async with maker() as session:
            await set_tenant_context(session, user_id)
            export = await session.scalar(
                sa.select(DataExportORM).where(
                    DataExportORM.id == export_id, DataExportORM.user_id == user_id
                )
            )
            if export is None:
                return None
            if export.status == "ready" and export.object_key:
                return export.object_key
            export.status = "processing"
            export.error_code = ""
            await session.commit()

            user = await session.get(UserORM, user_id)
            roles = list(
                (
                    await session.execute(
                        sa.select(UserRoleORM.role).where(UserRoleORM.user_id == user_id)
                    )
                )
                .scalars()
                .all()
            )
            projects = list(
                (await session.execute(sa.select(ProjectORM).where(ProjectORM.owner_id == user_id)))
                .scalars()
                .all()
            )
            project_ids = [project.id for project in projects]
            revisions = (
                list(
                    (
                        await session.execute(
                            sa.select(ProjectRevisionORM).where(
                                ProjectRevisionORM.project_id.in_(project_ids)
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                if project_ids
                else []
            )
            releases = list(
                (
                    await session.execute(
                        sa.select(ContentReleaseORM).where(ContentReleaseORM.owner_id == user_id)
                    )
                )
                .scalars()
                .all()
            )
            plays = list(
                (
                    await session.execute(
                        sa.select(PlaythroughORM).where(PlaythroughORM.user_id == user_id)
                    )
                )
                .scalars()
                .all()
            )
            session_ids = [play.game_session_id for play in plays if play.game_session_id]
            turns = (
                list(
                    (
                        await session.execute(
                            sa.select(TurnORM).where(TurnORM.session_id.in_(session_ids))
                        )
                    )
                    .scalars()
                    .all()
                )
                if session_ids
                else []
            )
            narratives = (
                list(
                    (
                        await session.execute(
                            sa.select(NarrativeSegmentORM).where(
                                NarrativeSegmentORM.session_id.in_(session_ids),
                                NarrativeSegmentORM.kind.in_(("chapter", "scene", "ending")),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                if session_ids
                else []
            )
            saves = list(
                (
                    await session.execute(
                        sa.select(SaveSlotORM).where(SaveSlotORM.user_id == user_id)
                    )
                )
                .scalars()
                .all()
            )
            usage = list(
                (
                    await session.execute(
                        sa.select(UsageLedgerORM).where(UsageLedgerORM.user_id == user_id)
                    )
                )
                .scalars()
                .all()
            )
            reports = list(
                (
                    await session.execute(
                        sa.select(ReportORM).where(ReportORM.reporter_id == user_id)
                    )
                )
                .scalars()
                .all()
            )
            support_cases = list(
                (
                    await session.execute(
                        sa.select(SupportCaseORM).where(SupportCaseORM.user_id == user_id)
                    )
                )
                .scalars()
                .all()
            )
            support_case_ids = [case.id for case in support_cases]
            support_messages = (
                list(
                    (
                        await session.execute(
                            sa.select(SupportCaseMessageORM).where(
                                SupportCaseMessageORM.case_id.in_(support_case_ids)
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                if support_case_ids
                else []
            )
            product_events = list(
                (
                    await session.execute(
                        sa.select(ProductEventORM).where(ProductEventORM.user_id == user_id)
                    )
                )
                .scalars()
                .all()
            )
            notifications = list(
                (
                    await session.execute(
                        sa.select(UserNotificationORM).where(
                            UserNotificationORM.user_id == user_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            payload = {
                "format": "narrative-personal-export-v1",
                "exported_at": datetime.now(UTC),
                "account": {
                    "id": user.id,
                    "email": user.email,
                    "display_name": user.display_name,
                    "locale": user.locale,
                    "status": user.status,
                    "roles": sorted(roles),
                    "product_analytics": user.analytics_consent,
                    "analytics_consent_updated_at": user.analytics_consent_updated_at,
                    "created_at": user.created_at,
                }
                if user
                else None,
                "projects": [
                    {
                        "id": row.id,
                        "slug": row.slug,
                        "title": row.title,
                        "summary": row.summary,
                        "status": row.status,
                        "current_revision": row.current_revision,
                        "created_at": row.created_at,
                    }
                    for row in projects
                ],
                "project_revisions": [
                    {
                        "project_id": row.project_id,
                        "revision": row.revision,
                        "document": row.document,
                        "diagnostics": row.diagnostics,
                        "created_at": row.created_at,
                    }
                    for row in revisions
                ],
                "releases": [
                    {
                        "id": row.id,
                        "project_id": row.project_id,
                        "version": row.version,
                        "checksum": row.checksum,
                        "visibility": row.visibility,
                        "moderation_status": row.moderation_status,
                        "artifact": row.artifact,
                        "created_at": row.created_at,
                    }
                    for row in releases
                ],
                "playthroughs": [
                    {
                        "id": row.id,
                        "release_id": row.release_id,
                        "scenario_key": row.scenario_key,
                        "name": row.name,
                        "status": row.status,
                        "ending_key": row.ending_key,
                        "player_config": row.player_config,
                        "created_at": row.created_at,
                    }
                    for row in plays
                ],
                "turns": [
                    {
                        "id": row.id,
                        "session_id": row.session_id,
                        "turn_number": row.turn_number,
                        "player_input": row.player_input,
                        "status": row.status,
                        "world_minute_before": row.world_minute_before,
                        "world_minute_after": row.world_minute_after,
                        "created_at": row.created_at,
                    }
                    for row in turns
                ],
                "narrative": [
                    {
                        "id": row.id,
                        "session_id": row.session_id,
                        "turn_id": row.turn_id,
                        "kind": row.kind,
                        "text": row.text,
                        "world_minute": row.world_minute,
                        "created_at": row.created_at,
                    }
                    for row in narratives
                ],
                # Snapshot payloads contain undiscovered NPC facts. Export only player-visible headers.
                "saves": [
                    {
                        "id": row.id,
                        "playthrough_id": row.playthrough_id,
                        "name": row.name,
                        "turn_number": row.turn_number,
                        "time_label": row.time_label,
                        "location_name": row.location_name,
                        "excerpt": row.excerpt,
                        "created_at": row.created_at,
                    }
                    for row in saves
                ],
                "usage": [
                    {
                        "playthrough_id": row.playthrough_id,
                        "provider": row.provider,
                        "model": row.model,
                        "input_tokens": row.input_tokens,
                        "output_tokens": row.output_tokens,
                        "cost_microunits": row.cost_microunits,
                        "success": row.success,
                        "created_at": row.created_at,
                    }
                    for row in usage
                ],
                "reports": [
                    {
                        "id": row.id,
                        "release_id": row.release_id,
                        "category": row.category,
                        "details": row.details,
                        "status": row.status,
                        "created_at": row.created_at,
                    }
                    for row in reports
                ],
                "support_cases": [
                    {
                        "id": row.id,
                        "playthrough_id": row.playthrough_id,
                        "category": row.category,
                        "status": row.status,
                        "priority": row.priority,
                        "subject": row.subject,
                        "created_at": row.created_at,
                        "updated_at": row.updated_at,
                    }
                    for row in support_cases
                ],
                "support_messages": [
                    {
                        "id": row.id,
                        "case_id": row.case_id,
                        "author_role": row.author_role,
                        "body": row.body,
                        "created_at": row.created_at,
                    }
                    for row in support_messages
                ],
                "product_events": [
                    {
                        "event_name": row.event_name,
                        "dedupe_key": row.dedupe_key,
                        "playthrough_id": row.playthrough_id,
                        "project_id": row.project_id,
                        "release_id": row.release_id,
                        "properties": row.event_properties,
                        "occurred_at": row.occurred_at,
                    }
                    for row in product_events
                ],
                "notifications": [
                    {
                        "id": row.id,
                        "kind": row.kind,
                        "title": row.title,
                        "body": row.body,
                        "href": row.href,
                        "read_at": row.read_at,
                        "created_at": row.created_at,
                    }
                    for row in notifications
                ],
            }
            encoded = json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                default=lambda value: (
                    value.isoformat() if isinstance(value, datetime) else str(value)
                ),
            ).encode("utf-8")
            object_key = f"{user_id}/exports/{export.id}.json"
            await object_store(settings).put(object_key, encoded, "application/json")
            export.object_key = object_key
            export.byte_size = len(encoded)
            export.status = "ready"
            export.expires_at = datetime.now(UTC) + timedelta(hours=24)
            await session.commit()
            return object_key
    except Exception as exc:
        async with maker() as failure_session:
            await set_tenant_context(failure_session, user_id)
            export = await failure_session.get(DataExportORM, export_id)
            if export is not None:
                export.status = "failed"
                export.error_code = type(exc).__name__[:80]
                await failure_session.commit()
        raise


async def cleanup_expired_exports(settings: Settings) -> int:
    maker = db_session.get_sessionmaker(settings)
    removed = 0
    async with maker() as session:
        user_ids = list((await session.execute(sa.select(UserORM.id))).scalars().all())
        for user_id in user_ids:
            await set_tenant_context(session, user_id)
            rows = list(
                (
                    await session.execute(
                        sa.select(DataExportORM).where(
                            DataExportORM.user_id == user_id,
                            DataExportORM.expires_at <= datetime.now(UTC),
                            DataExportORM.status == "ready",
                        )
                    )
                )
                .scalars()
                .all()
            )
            for row in rows:
                if row.object_key:
                    await object_store(settings).delete(row.object_key)
                row.object_key = None
                row.byte_size = 0
                row.status = "expired"
                removed += 1
        await session.commit()
    return removed
