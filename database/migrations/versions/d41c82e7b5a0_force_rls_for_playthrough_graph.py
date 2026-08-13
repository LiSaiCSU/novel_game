"""force RLS for projects and the complete playthrough graph

Revision ID: d41c82e7b5a0
Revises: c82fa6d40b31
Create Date: 2026-08-13 03:10:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d41c82e7b5a0"
down_revision: str | None = "c82fa6d40b31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_IDENTITY = "NULLIF(current_setting('app.current_user_id', true), '')"

_DIRECT_TENANT_TABLES = (
    "projects",
    "assets",
    "llm_credentials",
    "playthroughs",
    "usage_ledger",
    "save_slots",
)

_WORLD_TABLES = (
    "locations",
    "factions",
    "characters",
    "relationships",
    "relationship_changes",
    "facts",
    "memories",
    "items",
    "skills",
    "quests",
    "events",
    "director_events",
    "plot_threads",
    "turn_traces",
)


def _policy(table: str, expression: str) -> None:
    op.execute(sa.text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
    op.execute(sa.text(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY'))
    op.execute(
        sa.text(
            f'CREATE POLICY {table}_playthrough_policy ON "{table}" '
            f"USING ({expression}) WITH CHECK ({expression})"
        )
    )


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    for table in _DIRECT_TENANT_TABLES:
        op.execute(sa.text(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY'))

    _policy(
        "worlds",
        f"EXISTS (SELECT 1 FROM playthroughs p WHERE p.id = worlds.playthrough_id "
        f"AND p.user_id = {_IDENTITY})",
    )
    for table in _WORLD_TABLES:
        _policy(
            table,
            f"EXISTS (SELECT 1 FROM worlds w JOIN playthroughs p ON p.id = w.playthrough_id "
            f"WHERE w.id = {table}.world_id AND p.user_id = {_IDENTITY})",
        )

    for table, character_column in {
        "character_knowledge": "character_id",
        "inventory_items": "character_id",
        "character_skills": "character_id",
    }.items():
        _policy(
            table,
            f"EXISTS (SELECT 1 FROM characters c JOIN worlds w ON w.id = c.world_id "
            f"JOIN playthroughs p ON p.id = w.playthrough_id "
            f"WHERE c.id = {table}.{character_column} AND p.user_id = {_IDENTITY})",
        )

    _policy(
        "game_sessions",
        f"EXISTS (SELECT 1 FROM playthroughs p WHERE p.id = game_sessions.playthrough_id "
        f"AND p.user_id = {_IDENTITY})",
    )
    for table in ("turns", "narrative_segments"):
        _policy(
            table,
            f"EXISTS (SELECT 1 FROM game_sessions s JOIN playthroughs p "
            f"ON p.id = s.playthrough_id WHERE s.id = {table}.session_id "
            f"AND p.user_id = {_IDENTITY})",
        )

    _policy(
        "project_revisions",
        f"EXISTS (SELECT 1 FROM projects p WHERE p.id = project_revisions.project_id "
        f"AND p.owner_id = {_IDENTITY})",
    )
    op.execute(
        sa.text(
            "CREATE POLICY projects_public_read_policy ON projects FOR SELECT "
            "USING (status = 'published' OR share_token_hash IS NOT NULL)"
        )
    )
    reviewer = (
        "EXISTS (SELECT 1 FROM user_roles ur WHERE ur.user_id = "
        f"{_IDENTITY} AND ur.role IN ('reviewer', 'admin'))"
    )
    op.execute(
        sa.text(
            "CREATE POLICY projects_reviewer_read_policy ON projects FOR SELECT "
            f"USING ({reviewer})"
        )
    )
    op.execute(
        sa.text(
            "CREATE POLICY projects_reviewer_update_policy ON projects FOR UPDATE "
            f"USING ({reviewer}) WITH CHECK ({reviewer})"
        )
    )
    op.execute(
        sa.text(
            "CREATE POLICY project_revisions_shared_read_policy ON project_revisions FOR SELECT "
            "USING (EXISTS (SELECT 1 FROM projects p WHERE p.id = project_id "
            "AND p.share_token_hash IS NOT NULL))"
        )
    )
    op.execute(
        sa.text(
            "CREATE POLICY assets_public_read_policy ON assets FOR SELECT "
            "USING (EXISTS (SELECT 1 FROM content_releases r WHERE r.project_id = assets.project_id "
            "AND r.visibility = 'public' AND r.moderation_status = 'approved' "
            "AND r.withdrawn_at IS NULL))"
        )
    )
    op.execute(sa.text('ALTER TABLE "content_releases" ENABLE ROW LEVEL SECURITY'))
    op.execute(sa.text('ALTER TABLE "content_releases" FORCE ROW LEVEL SECURITY'))
    op.execute(
        sa.text(
            "CREATE POLICY content_releases_read_policy ON content_releases FOR SELECT "
            f"USING (owner_id = {_IDENTITY} OR visibility = 'unlisted' OR (visibility = 'public' "
            "AND moderation_status = 'approved' AND withdrawn_at IS NULL))"
        )
    )
    op.execute(
        sa.text(
            "CREATE POLICY content_releases_reviewer_read_policy ON content_releases FOR SELECT "
            f"USING ({reviewer})"
        )
    )
    op.execute(
        sa.text(
            "CREATE POLICY content_releases_reviewer_update_policy ON content_releases FOR UPDATE "
            f"USING ({reviewer}) WITH CHECK ({reviewer})"
        )
    )
    op.execute(
        sa.text(
            "CREATE POLICY content_releases_owner_policy ON content_releases FOR ALL "
            f"USING (owner_id = {_IDENTITY}) WITH CHECK (owner_id = {_IDENTITY})"
        )
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute(sa.text("DROP POLICY IF EXISTS content_releases_reviewer_update_policy ON content_releases"))
    op.execute(sa.text("DROP POLICY IF EXISTS content_releases_reviewer_read_policy ON content_releases"))
    op.execute(sa.text("DROP POLICY IF EXISTS content_releases_owner_policy ON content_releases"))
    op.execute(sa.text("DROP POLICY IF EXISTS content_releases_read_policy ON content_releases"))
    op.execute(sa.text('ALTER TABLE "content_releases" NO FORCE ROW LEVEL SECURITY'))
    op.execute(sa.text("DROP POLICY IF EXISTS assets_public_read_policy ON assets"))
    op.execute(sa.text("DROP POLICY IF EXISTS project_revisions_shared_read_policy ON project_revisions"))
    op.execute(sa.text("DROP POLICY IF EXISTS projects_reviewer_update_policy ON projects"))
    op.execute(sa.text("DROP POLICY IF EXISTS projects_reviewer_read_policy ON projects"))
    op.execute(sa.text("DROP POLICY IF EXISTS projects_public_read_policy ON projects"))
    for table in ("project_revisions", "narrative_segments", "turns", "game_sessions"):
        op.execute(sa.text(f'DROP POLICY IF EXISTS {table}_playthrough_policy ON "{table}"'))
        op.execute(sa.text(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY'))
    for table in ("character_knowledge", "inventory_items", "character_skills"):
        op.execute(sa.text(f'DROP POLICY IF EXISTS {table}_playthrough_policy ON "{table}"'))
        op.execute(sa.text(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY'))
    for table in reversed(_WORLD_TABLES):
        op.execute(sa.text(f'DROP POLICY IF EXISTS {table}_playthrough_policy ON "{table}"'))
        op.execute(sa.text(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY'))
    op.execute(sa.text("DROP POLICY IF EXISTS worlds_playthrough_policy ON worlds"))
    op.execute(sa.text('ALTER TABLE "worlds" NO FORCE ROW LEVEL SECURITY'))
    for table in _DIRECT_TENANT_TABLES:
        op.execute(sa.text(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY'))
