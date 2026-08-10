"""Stable extension boundary for trusted content-pack rule code."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from engine.actions.schema import Action, ActionOutcome, RuleResult
    from engine.core.mutations import ChangeSet
    from engine.core.types import ActionType
    from engine.events.builder import EventBuilder
    from engine.rules.base import RuleContext

RULE_PLUGIN_API_VERSION = "1"


@runtime_checkable
class RulePlugin(Protocol):
    """Deterministic, side-effect-free domain rules supplied by a trusted pack.

    Plugins may inspect the immutable RuleContext and return ChangeSet proposals.
    They receive no repository or UnitOfWork, so they cannot commit canonical state.
    """

    key: str
    api_version: str
    handled_actions: frozenset[ActionType]

    def validate_action(self, ctx: RuleContext, action: Action) -> RuleResult: ...

    def resolve_action(
        self,
        ctx: RuleContext,
        action: Action,
        rule_result: RuleResult,
        events: EventBuilder,
    ) -> tuple[ActionOutcome, ChangeSet]: ...
