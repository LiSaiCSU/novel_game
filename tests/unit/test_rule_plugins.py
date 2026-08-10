from __future__ import annotations

import pytest

from engine.actions.resolver import ActionResolver
from engine.actions.schema import Action, ActionOutcome, RuleResult
from engine.contentpack.plugin_loader import load_rule_plugin
from engine.core.errors import ContentPackError
from engine.core.mutations import ChangeSet
from engine.core.types import ActionType
from engine.events.builder import EventBuilder
from engine.relationships.manager import RelationshipManager
from engine.rules.engine import RuleEngine


class InvestigationPlugin:
    """A non-cultivation domain rule used to prove the generic boundary."""

    key = "investigation"
    api_version = "1"
    handled_actions = frozenset({ActionType.CUSTOM})

    def validate_action(self, ctx, action):
        return RuleResult.ok(domain="investigation")

    def resolve_action(self, ctx, action, rule_result, events):
        changes = ChangeSet()
        changes.add_event(
            events.build(
                "CLUE_EXAMINED",
                actor_id=action.actor_id,
                payload={"clue_key": action.parameters["clue_key"]},
                world_minute=ctx.now,
            )
        )
        return (
            ActionOutcome(
                action_type=action.action_type,
                success=True,
                summary_key="CLUE_EXAMINED",
                facts={"clue_key": action.parameters["clue_key"]},
            ),
            changes,
        )


def test_non_cultivation_plugin_owns_validation_and_resolution(pack, ctx) -> None:
    original_plugin = pack.rule_plugin
    pack.rule_plugin = InvestigationPlugin()
    action = Action(
        action_type=ActionType.CUSTOM,
        actor_id=ctx.state.player.id,
        parameters={"clue_key": "muddy_footprint"},
    )
    rules = RuleEngine()
    resolver = ActionResolver(
        EventBuilder(pack, ctx.state.world.id, "plugin-turn"),
        RelationshipManager(pack),
    )

    try:
        verdict = rules.validate_action(ctx, action)
        outcome, changes = resolver.resolve(ctx, action, verdict)
    finally:
        pack.rule_plugin = original_plugin

    assert verdict.details == {"domain": "investigation"}
    assert outcome.summary_key == "CLUE_EXAMINED"
    assert changes.events[0].event_type == "CLUE_EXAMINED"
    assert changes.events[0].payload == {"clue_key": "muddy_footprint"}


def test_cultivation_pack_declares_a_versioned_rule_plugin(pack) -> None:
    assert pack.rule_plugin is not None
    assert pack.rule_plugin.key == "cultivation"
    assert pack.rule_plugin.api_version == "1"
    assert pack.rule_plugin.handled_actions == frozenset(
        {ActionType.CULTIVATE, ActionType.BREAKTHROUGH}
    )


def test_rule_plugin_path_cannot_escape_pack(tmp_path) -> None:
    with pytest.raises(ContentPackError, match="escapes the content pack"):
        load_rule_plugin(
            tmp_path,
            {
                "rule_plugin": {
                    "path": "../outside.py",
                    "class": "OutsidePlugin",
                    "api_version": "1",
                }
            },
        )


def test_rule_plugin_api_version_must_match(tmp_path) -> None:
    with pytest.raises(ContentPackError, match="unsupported rule plugin API"):
        load_rule_plugin(
            tmp_path,
            {
                "rule_plugin": {
                    "path": "rule_plugin.py",
                    "class": "FuturePlugin",
                    "api_version": "999",
                }
            },
        )


def test_rule_plugin_can_import_sibling_domain_modules(tmp_path) -> None:
    (tmp_path / "domain.py").write_text("PLUGIN_KEY = 'portable-investigation'\n", encoding="utf-8")
    (tmp_path / "entry.py").write_text(
        """
from .domain import PLUGIN_KEY
from engine.core.types import ActionType

class PortablePlugin:
    key = PLUGIN_KEY
    api_version = "1"
    handled_actions = frozenset({ActionType.CUSTOM})

    def validate_action(self, ctx, action):
        raise NotImplementedError

    def resolve_action(self, ctx, action, rule_result, events):
        raise NotImplementedError
""".lstrip(),
        encoding="utf-8",
    )

    plugin = load_rule_plugin(
        tmp_path,
        {
            "rule_plugin": {
                "path": "entry.py",
                "class": "PortablePlugin",
                "api_version": "1",
            }
        },
    )

    assert plugin is not None
    assert plugin.key == "portable-investigation"
