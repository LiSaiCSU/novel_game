"""InventoryRules and EconomyRules (Prompt sections 36, 8).

The LLM has no power to add items. Everything here is checked against the
inventory rows that actually exist.
"""

from __future__ import annotations

from engine.actions.schema import RuleResult
from engine.core.models import Character, InventoryItem
from engine.core.types import ReasonCode
from engine.rules.base import RuleContext, clamp


class InventoryRules:
    @staticmethod
    def owned_quantity(inventory: list[InventoryItem], item_key: str) -> int:
        return sum(row.quantity for row in inventory if row.item_key == item_key)

    @staticmethod
    def validate_has_item(
        ctx: RuleContext, inventory: list[InventoryItem], item_key: str | None, quantity: int = 1
    ) -> RuleResult:
        if not item_key:
            return RuleResult.deny(ReasonCode.ITEM_NOT_OWNED, "no item specified")
        if ctx.pack.item(item_key) is None:
            return RuleResult.deny(ReasonCode.ITEM_NOT_OWNED, f"no such item {item_key}")
        owned = InventoryRules.owned_quantity(inventory, item_key)
        if owned < quantity:
            return RuleResult.deny(
                ReasonCode.ITEM_NOT_OWNED,
                f"does not own {quantity} of {item_key}",
                item_key=item_key,
                owned=owned,
                required=quantity,
            )
        return RuleResult.ok(item_key=item_key, owned=owned)

    @staticmethod
    def validate_capacity(
        ctx: RuleContext, inventory: list[InventoryItem], item_key: str
    ) -> RuleResult:
        max_slots = int(ctx.rule("inventory.max_slots", 40))
        distinct = {row.item_key for row in inventory}
        if item_key in distinct:
            return RuleResult.ok()
        if len(distinct) >= max_slots:
            return RuleResult.deny(
                ReasonCode.INVENTORY_FULL, "no free inventory slot", max_slots=max_slots
            )
        return RuleResult.ok()

    @staticmethod
    def validate_use_item(
        ctx: RuleContext, character: Character, inventory: list[InventoryItem], item_key: str | None
    ) -> RuleResult:
        has = InventoryRules.validate_has_item(ctx, inventory, item_key)
        if not has.allowed:
            return has
        raw = ctx.pack.item(item_key or "")
        assert raw is not None  # guarded by validate_has_item
        effects = raw.get("effects", {}) or {}
        applies_to = effects.get("applies_to_realm")
        if applies_to and applies_to != character.realm:
            return RuleResult.deny(
                ReasonCode.NOT_PHYSICALLY_POSSIBLE,
                "this item has no effect at the character's tier",
                item_key=item_key,
                applies_to_realm=applies_to,
                actual_realm=character.realm,
            )
        return RuleResult.ok(effects=effects)


class EconomyRules:
    @staticmethod
    def currency_key(ctx: RuleContext) -> str:
        return str(ctx.rule("economy.currency_key", "currency"))

    @staticmethod
    def base_value(ctx: RuleContext, item_key: str) -> int:
        raw = ctx.pack.item(item_key)
        return int(raw.get("value", 0)) if raw else 0

    @staticmethod
    def calculate_price(
        ctx: RuleContext, item_key: str, *, buying: bool, reputation: float = 0.0
    ) -> int:
        value = EconomyRules.base_value(ctx, item_key)
        if value <= 0:
            return 0
        markup = float(ctx.rule("economy.buy_markup", 1.0))
        discount = float(ctx.rule("economy.sell_discount", 0.5))
        rep_weight = float(ctx.rule("economy.reputation_price_weight", 0.0))
        modifier = 1.0 - clamp(reputation * rep_weight, -0.25, 0.25)
        price = value * (markup if buying else discount) * (modifier if buying else 1.0)
        return max(1, round(price))

    @staticmethod
    def validate_purchase(
        ctx: RuleContext,
        inventory: list[InventoryItem],
        item_key: str | None,
        quantity: int,
        price_each: int,
    ) -> RuleResult:
        if not item_key or ctx.pack.item(item_key) is None:
            return RuleResult.deny(ReasonCode.NOT_FOR_SALE, "no such item")
        if price_each <= 0:
            return RuleResult.deny(ReasonCode.NOT_FOR_SALE, "item is not for sale")
        currency = EconomyRules.currency_key(ctx)
        funds = InventoryRules.owned_quantity(inventory, currency)
        total = price_each * max(1, quantity)
        if funds < total:
            return RuleResult.deny(
                ReasonCode.INSUFFICIENT_FUNDS,
                "not enough currency",
                required=total,
                available=funds,
            )
        capacity = InventoryRules.validate_capacity(ctx, inventory, item_key)
        if not capacity.allowed:
            return capacity
        return RuleResult.ok(total=total, currency=currency)

    @staticmethod
    def validate_sale(
        ctx: RuleContext, inventory: list[InventoryItem], item_key: str | None, quantity: int
    ) -> RuleResult:
        has = InventoryRules.validate_has_item(ctx, inventory, item_key, quantity)
        if not has.allowed:
            return has
        if item_key == EconomyRules.currency_key(ctx):
            return RuleResult.deny(ReasonCode.NOT_FOR_SALE, "cannot sell currency")
        return RuleResult.ok()
