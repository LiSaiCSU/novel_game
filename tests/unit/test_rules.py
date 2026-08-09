"""Rule tests (Prompt section 61).

These are the "the world can say no" tests. Every one of them must hold with no
LLM involved at all.
"""

from __future__ import annotations

import pytest

from engine.actions.schema import Action
from engine.contentpack.pack import ContentPack
from engine.core.types import ActionType, ReasonCode, RequestSize
from engine.rules.base import RuleContext
from engine.rules.combat import CombatRules, DetectionRules, SkillRules
from engine.rules.cultivation import CultivationRules
from engine.rules.economy import EconomyRules, InventoryRules
from engine.rules.engine import RuleEngine
from engine.rules.interaction import InteractionRules
from engine.world.state_view import WorldStateView


@pytest.fixture
def engine() -> RuleEngine:
    return RuleEngine()


# ---------------------------------------------------------------------------
# Realm gating
# ---------------------------------------------------------------------------
def test_low_realm_cannot_use_high_realm_skill(ctx: RuleContext, pack: ContentPack) -> None:
    """A qi-refining cultivator may not use a foundation-tier technique."""
    player = ctx.state.player
    high_skill = next(
        s
        for s in pack.skills
        if pack.realms.order(str(s["required_realm"])) > pack.realms.order(player.realm)
    )
    result = SkillRules.validate_use(
        ctx, player, str(high_skill["key"]), learned=True, last_used_minute=-10**9
    )
    assert not result.allowed
    assert result.reason_code is ReasonCode.REALM_TOO_LOW


def test_unlearned_skill_is_rejected(ctx: RuleContext, engine: RuleEngine, pack: ContentPack) -> None:
    unknown = next(s["key"] for s in pack.skills if not ctx.state.has_skill(str(s["key"])))
    action = Action(
        action_type=ActionType.USE_SKILL, actor_id=ctx.state.player.id, skill_key=str(unknown)
    )
    result = engine.validate_action(ctx, action)
    assert not result.allowed
    assert result.reason_code is ReasonCode.SKILL_NOT_LEARNED


def test_insufficient_spiritual_power_is_rejected(ctx: RuleContext, pack: ContentPack) -> None:
    player = ctx.state.player
    skill_key = next(iter(s.skill_key for s in ctx.state.known_skills))
    player.spiritual_power = 0
    result = SkillRules.validate_use(ctx, player, skill_key, learned=True, last_used_minute=-10**9)
    raw = pack.skill(skill_key) or {}
    if int(raw.get("spiritual_cost", 0)) > 0:
        assert not result.allowed
        assert result.reason_code is ReasonCode.INSUFFICIENT_SPIRITUAL_POWER


def test_skill_cooldown_is_enforced(ctx: RuleContext, pack: ContentPack) -> None:
    player = ctx.state.player
    skill_key = next(
        s.skill_key
        for s in ctx.state.known_skills
        if int((pack.skill(s.skill_key) or {}).get("cooldown_minutes", 0)) > 0
    )
    result = SkillRules.validate_use(ctx, player, skill_key, learned=True, last_used_minute=ctx.now)
    assert not result.allowed
    assert result.reason_code is ReasonCode.SKILL_ON_COOLDOWN


# ---------------------------------------------------------------------------
# Death and presence
# ---------------------------------------------------------------------------
def test_dead_actor_cannot_act(ctx: RuleContext, engine: RuleEngine) -> None:
    ctx.state.player.alive = False
    action = Action(action_type=ActionType.OBSERVE, actor_id=ctx.state.player.id)
    result = engine.validate_action(ctx, action)
    assert not result.allowed
    assert result.reason_code is ReasonCode.ACTOR_DEAD


def test_dead_target_cannot_be_attacked(ctx: RuleContext, engine: RuleEngine) -> None:
    target = ctx.state.present_characters[0]
    target.alive = False
    action = Action(action_type=ActionType.ATTACK, actor_id=ctx.state.player.id, target_id=target.id)
    result = engine.validate_action(ctx, action)
    assert not result.allowed
    assert result.reason_code is ReasonCode.TARGET_DEAD


def test_cannot_melee_someone_elsewhere(ctx: RuleContext, state: WorldStateView) -> None:
    target = state.present_characters[0]
    target.location_id = "somewhere-else"
    result = CombatRules.validate_attack(ctx, state.player, target)
    assert not result.allowed
    assert result.reason_code is ReasonCode.TARGET_NOT_PRESENT


def test_cannot_talk_to_someone_elsewhere(ctx: RuleContext, engine: RuleEngine) -> None:
    target = ctx.state.present_characters[0]
    target.location_id = "far-away"
    action = Action(action_type=ActionType.TALK, actor_id=ctx.state.player.id, target_id=target.id)
    result = engine.validate_action(ctx, action)
    assert not result.allowed
    assert result.reason_code is ReasonCode.TARGET_NOT_PRESENT


# ---------------------------------------------------------------------------
# Items and money
# ---------------------------------------------------------------------------
def test_cannot_use_an_item_you_do_not_have(ctx: RuleContext, engine: RuleEngine, pack: ContentPack) -> None:
    owned = {row.item_key for row in ctx.state.inventory}
    missing = next(i["key"] for i in pack.items if i["key"] not in owned)
    action = Action(action_type=ActionType.USE_ITEM, actor_id=ctx.state.player.id, item_key=str(missing))
    result = engine.validate_action(ctx, action)
    assert not result.allowed
    assert result.reason_code is ReasonCode.ITEM_NOT_OWNED


def test_cannot_buy_without_funds(ctx: RuleContext, pack: ContentPack) -> None:
    currency = EconomyRules.currency_key(ctx)
    expensive = max(pack.items, key=lambda i: int(i.get("value", 0)))
    price = EconomyRules.calculate_price(ctx, str(expensive["key"]), buying=True)
    result = EconomyRules.validate_purchase(
        ctx, ctx.state.inventory, str(expensive["key"]), 1, price
    )
    assert not result.allowed
    assert result.reason_code is ReasonCode.INSUFFICIENT_FUNDS
    assert result.details["required"] > result.details["available"]
    assert currency


def test_inventory_quantity_is_authoritative(ctx: RuleContext) -> None:
    currency = EconomyRules.currency_key(ctx)
    owned = InventoryRules.owned_quantity(ctx.state.inventory, currency)
    ok = InventoryRules.validate_has_item(ctx, ctx.state.inventory, currency, owned)
    too_many = InventoryRules.validate_has_item(ctx, ctx.state.inventory, currency, owned + 1)
    assert ok.allowed
    assert not too_many.allowed


# ---------------------------------------------------------------------------
# Cultivation
# ---------------------------------------------------------------------------
def test_breakthrough_requires_full_progress(ctx: RuleContext) -> None:
    ctx.state.player.cultivation_progress = 0.5
    result = CultivationRules.validate_breakthrough(ctx, ctx.state.player)
    assert not result.allowed
    assert result.reason_code is ReasonCode.CULTIVATION_NOT_READY


def test_breakthrough_allowed_at_full_progress(ctx: RuleContext) -> None:
    ctx.state.player.cultivation_progress = 1.0
    result = CultivationRules.validate_breakthrough(ctx, ctx.state.player)
    assert result.allowed
    assert result.details["to_realm"]


def test_breakthrough_odds_stay_in_bounds(ctx: RuleContext) -> None:
    player = ctx.state.player
    player.injuries = 1.0
    player.mental_state = 0.0
    player.bottleneck = 0.6
    low = CultivationRules.calculate_breakthrough(ctx, player)
    assert 0.0 < low.chance <= 1.0
    assert low.chance <= ctx.rule("breakthrough.max_chance", 0.95)

    player.injuries = 0.0
    player.mental_state = 1.0
    player.bottleneck = 0.0
    high = CultivationRules.calculate_breakthrough(ctx, player, pill_bonus=0.9)
    assert high.chance > low.chance
    assert high.chance <= ctx.rule("breakthrough.max_chance", 0.95)


def test_higher_spirit_density_speeds_cultivation(ctx: RuleContext) -> None:
    player = ctx.state.player
    location = ctx.state.graph.by_id(player.location_id)
    assert location is not None
    baseline = CultivationRules.calculate_gain(ctx, player, 240).xp_ratio
    location.spirit_density *= 3
    boosted = CultivationRules.calculate_gain(ctx, player, 240).xp_ratio
    assert boosted > baseline


def test_cultivation_has_diminishing_returns(ctx: RuleContext) -> None:
    player = ctx.state.player
    short = CultivationRules.calculate_gain(ctx, player, 240)
    long = CultivationRules.calculate_gain(ctx, player, 240 * 60)
    assert long.diminished
    assert long.xp_ratio <= ctx.rule("cultivation.max_xp_ratio_per_session", 0.85)
    assert not short.diminished


def test_seclusion_beyond_the_cap_is_rejected(ctx: RuleContext) -> None:
    cap = int(ctx.rule("time_costs.SECLUSION_MAX_MINUTES", 1_555_200))
    result = CultivationRules.validate_cultivate(ctx, ctx.state.player, cap + 1)
    assert not result.allowed
    assert result.reason_code is ReasonCode.TIME_LIMIT_EXCEEDED


# ---------------------------------------------------------------------------
# Combat maths
# ---------------------------------------------------------------------------
def test_two_tier_gap_makes_damage_negligible(ctx: RuleContext, pack: ContentPack) -> None:
    """Eval 1: a qi-refining cultivator cannot one-shot a far stronger being."""
    attacker = ctx.state.player
    defender = ctx.state.present_characters[0].model_copy(deep=True)
    top = pack.realms.realms[-1]
    defender.realm = top.key
    defender.realm_stage = top.stages[-1].key
    defender.max_health = pack.realms.max_health(defender.realm, defender.realm_stage)
    defender.health = defender.max_health
    defender.location_id = attacker.location_id

    resolution = CombatRules.calculate_damage(ctx, attacker, defender)
    assert resolution.hard_blocked
    assert resolution.damage < defender.health * 0.05
    assert not resolution.lethal


def test_higher_realm_hits_much_harder(ctx: RuleContext, pack: ContentPack) -> None:
    weak = ctx.state.player
    strong = weak.model_copy(deep=True)
    strong.realm = pack.realms.realms[2].key
    strong.realm_stage = pack.realms.realms[2].stages[0].key
    strong.location_id = weak.location_id

    strong_hit = CombatRules.calculate_damage(ctx, strong, weak)
    weak_hit = CombatRules.calculate_damage(ctx, weak, strong)
    assert strong_hit.breakdown["multiplier"] > weak_hit.breakdown["multiplier"]


def test_detection_rises_with_observers(ctx: RuleContext) -> None:
    actor = ctx.state.player
    one = DetectionRules.calculate_detection(ctx, actor, ctx.state.present_characters[:1])
    many = DetectionRules.calculate_detection(
        ctx, actor, ctx.state.present_characters[:1] * 5
    )
    assert many >= one


# ---------------------------------------------------------------------------
# Social
# ---------------------------------------------------------------------------
def test_stranger_refuses_an_extreme_request(ctx: RuleContext) -> None:
    """Eval 3: 'give me your life savings' on a first meeting."""
    target = ctx.state.present_characters[0]
    odds = InteractionRules.calculate_probability(
        ctx,
        ctx.state.player,
        target,
        relationship=None,
        request_size=RequestSize.EXTREME,
        risk_to_target=0.8,
    )
    assert odds.chance < 0.15


def test_trusted_friend_grants_a_small_favour_more_easily(ctx: RuleContext) -> None:
    from engine.core.models import Relationship

    target = ctx.state.present_characters[0]
    friendly = Relationship(
        character_a_id=target.id,
        character_b_id=ctx.state.player.id,
        trust=80,
        affection=70,
        respect=60,
        familiarity=90,
    )
    friendly_odds = InteractionRules.calculate_probability(
        ctx, ctx.state.player, target, friendly, request_size=RequestSize.SMALL
    )
    stranger_odds = InteractionRules.calculate_probability(
        ctx, ctx.state.player, target, None, request_size=RequestSize.SMALL
    )
    assert friendly_odds.chance > stranger_odds.chance


def test_taboo_request_is_a_hard_refusal(ctx: RuleContext) -> None:
    target = ctx.state.present_characters[0]
    odds = InteractionRules.calculate_probability(
        ctx, ctx.state.player, target, None, violates_taboo=True
    )
    assert odds.hard_refusal
    assert odds.chance <= 0.01


def test_bigger_requests_are_always_harder(ctx: RuleContext) -> None:
    target = ctx.state.present_characters[0]
    sizes = [RequestSize.TRIVIAL, RequestSize.SMALL, RequestSize.MODERATE, RequestSize.LARGE, RequestSize.EXTREME]
    chances = [
        InteractionRules.calculate_probability(ctx, ctx.state.player, target, None, request_size=s).chance
        for s in sizes
    ]
    assert chances == sorted(chances, reverse=True)


# ---------------------------------------------------------------------------
# Movement
# ---------------------------------------------------------------------------
def test_movement_to_unknown_place_is_rejected(ctx: RuleContext, engine: RuleEngine) -> None:
    action = Action(
        action_type=ActionType.MOVE, actor_id=ctx.state.player.id, target_location_id="nowhere"
    )
    result = engine.validate_action(ctx, action)
    assert not result.allowed
    assert result.reason_code is ReasonCode.LOCATION_NOT_FOUND


def test_movement_finds_a_route_and_costs_time(ctx: RuleContext, engine: RuleEngine) -> None:
    here = ctx.state.location_key()
    far = next(
        loc for loc in ctx.state.graph.all() if loc.key != here and loc.accessible and loc.travel_minutes
    )
    action = Action(
        action_type=ActionType.MOVE, actor_id=ctx.state.player.id, target_location_id=far.id
    )
    result = engine.validate_action(ctx, action)
    assert result.allowed
    assert result.details["minutes"] > 0
    assert result.details["path"][0] == here
    assert result.details["path"][-1] == far.key


def test_inaccessible_location_is_locked(ctx: RuleContext, engine: RuleEngine) -> None:
    locked = next((loc for loc in ctx.state.graph.all() if not loc.accessible), None)
    if locked is None:
        pytest.skip("content pack has no locked location")
    action = Action(
        action_type=ActionType.MOVE, actor_id=ctx.state.player.id, target_location_id=locked.id
    )
    result = engine.validate_action(ctx, action)
    assert not result.allowed
    assert result.reason_code is ReasonCode.LOCATION_LOCKED


def test_available_actions_never_include_unusable_ones(ctx: RuleContext, engine: RuleEngine) -> None:
    allowed = engine.available_actions(ctx, ctx.state.player.id)
    assert str(ActionType.OBSERVE) in allowed
    assert str(ActionType.BREAKTHROUGH) not in allowed
