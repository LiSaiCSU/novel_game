"""Usage-based wallet billing with a durable preauthorization boundary.

The module is deliberately processor-agnostic.  It turns a verified internal
wallet balance into a short turn reservation and settles that reservation from
the actual LLM usage record.  Payment providers may later credit the same
wallet ledger, but they never participate in gameplay transactions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import ceil
from typing import Any, Literal

import sqlalchemy as sa
from fastapi import HTTPException

from apps.api.metrics import commerce_metrics
from apps.api.platform_settings import read_setting
from database.models.platform import UserORM, WalletHoldORM, WalletLedgerORM
from database.repositories.sql import SqlUnitOfWork
from engine.core.ids import new_id

COMMERCE_BILLING_KEY = "commerce_billing_policy"
DEFAULT_BILLING_POLICY: dict[str, Any] = {
    "mode": "disabled",
    "credit_label": "叙点",
    # The LLM price table expresses costs in millionths of the deployed
    # currency.  One credit maps to 10,000 microunits by default (one cent for
    # a CNY deployment), but the operator must disclose and explicitly enable
    # this policy before it can charge a player.
    "cost_microunits_per_credit": 10_000,
    "turn_reserve_credits": 100,
    "hold_minutes": 20,
}


class InsufficientWalletCredits(RuntimeError):
    """Raised before an external model request, never after a story changes."""


@dataclass(frozen=True, slots=True)
class BillingPolicy:
    mode: Literal["disabled", "wallet"] = "disabled"
    credit_label: str = "叙点"
    cost_microunits_per_credit: int = 10_000
    turn_reserve_credits: int = 100
    hold_minutes: int = 20

    @property
    def enabled(self) -> bool:
        return self.mode == "wallet"

    @classmethod
    def from_value(cls, value: dict[str, Any]) -> BillingPolicy:
        mode = str(value.get("mode", "disabled"))
        credit_label = str(value.get("credit_label", "叙点")).strip()[:24] or "叙点"
        try:
            rate = int(value.get("cost_microunits_per_credit", 10_000))
            reserve = int(value.get("turn_reserve_credits", 100))
            hold_minutes = int(value.get("hold_minutes", 20))
        except (TypeError, ValueError):
            return cls()
        if mode not in {"disabled", "wallet"} or rate < 1 or reserve < 1 or not 1 <= hold_minutes <= 120:
            return cls()
        return cls(
            mode="wallet" if mode == "wallet" else "disabled",
            credit_label=credit_label,
            cost_microunits_per_credit=rate,
            turn_reserve_credits=reserve,
            hold_minutes=hold_minutes,
        )

    def public_view(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "enabled": self.enabled,
            "credit_label": self.credit_label,
            "cost_microunits_per_credit": self.cost_microunits_per_credit,
            "turn_reserve_credits": self.turn_reserve_credits,
            "hold_minutes": self.hold_minutes,
        }


@dataclass(frozen=True, slots=True)
class TurnReservation:
    hold_id: str
    user_id: str
    idempotency_key: str
    reserved_credits: int
    cost_microunits_per_credit: int


async def billing_policy(uow: SqlUnitOfWork) -> BillingPolicy:
    return BillingPolicy.from_value(
        await read_setting(uow, COMMERCE_BILLING_KEY, DEFAULT_BILLING_POLICY)
    )


async def wallet_balance(uow: SqlUnitOfWork, user_id: str) -> int:
    return int(
        await uow.session.scalar(
            sa.select(sa.func.coalesce(sa.func.sum(WalletLedgerORM.credit_delta), 0)).where(
                WalletLedgerORM.user_id == user_id
            )
        )
        or 0
    )


async def _reserved_credits(uow: SqlUnitOfWork, user_id: str, now: datetime) -> int:
    return int(
        await uow.session.scalar(
            sa.select(sa.func.coalesce(sa.func.sum(WalletHoldORM.reserved_credits), 0)).where(
                WalletHoldORM.user_id == user_id,
                WalletHoldORM.status == "held",
                WalletHoldORM.expires_at > now,
            )
        )
        or 0
    )


async def wallet_available_credits(uow: SqlUnitOfWork, user_id: str) -> int:
    """Return the spendable balance after active turn preauthorizations.

    Administrative debits use this same value, so a privileged correction
    cannot take credits which a concurrent model turn has already reserved.
    """

    now = datetime.now(UTC)
    return await wallet_balance(uow, user_id) - await _reserved_credits(uow, user_id, now)


async def reserve_turn_credits(
    uow: SqlUnitOfWork,
    *,
    user_id: str,
    playthrough_id: str | None,
    idempotency_key: str | None,
    reservation_kind: Literal["turn", "opening", "creator"] = "turn",
) -> TurnReservation | None:
    """Lock available credit before a platform model can be called.

    Reservations are committed before inference because an LLM request can run
    for tens of seconds.  No world mutation has happened at this point, so the
    intentional transaction boundary cannot leave a story half-committed.
    """

    policy = await billing_policy(uow)
    if not policy.enabled:
        commerce_metrics.reservation("disabled")
        return None
    if not idempotency_key:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "idempotency_key_required_for_billing",
                "message": "启用叙点结算时必须提供幂等键。",
            },
        )
    now = datetime.now(UTC)
    user = await uow.session.scalar(sa.select(UserORM).where(UserORM.id == user_id).with_for_update())
    if user is None or user.status != "active":
        raise HTTPException(status_code=409, detail="account is not active")
    existing = await uow.session.scalar(
        sa.select(WalletHoldORM).where(
            WalletHoldORM.user_id == user_id,
            WalletHoldORM.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.status in {"settled", "capped"} or (
            existing.status == "held" and existing.expires_at > now
        ):
            commerce_metrics.reservation("idempotent_replay")
            return TurnReservation(
                hold_id=existing.id,
                user_id=user_id,
                idempotency_key=idempotency_key,
                reserved_credits=existing.reserved_credits,
                cost_microunits_per_credit=existing.cost_microunits_per_credit,
            )
        # A released or expired hold represents a failed request, not a free
        # retry.  A settled/capped hold above is a normal completed-action
        # replay and is therefore safe.  Clients must generate a new key for
        # a new attempt after a release.
        commerce_metrics.reservation("reused_terminal_key")
        raise HTTPException(
            status_code=409,
            detail={
                "code": "billing_idempotency_key_unavailable",
                "message": "该回合请求已结束，请使用新的幂等键重试。",
            },
        )

    await uow.session.execute(
        sa.update(WalletHoldORM)
        .where(
            WalletHoldORM.user_id == user_id,
            WalletHoldORM.status == "held",
            WalletHoldORM.expires_at <= now,
        )
        .values(status="released", hold_metadata={"release_reason": "expired"})
    )
    available = await wallet_available_credits(uow, user_id)
    if available < policy.turn_reserve_credits:
        commerce_metrics.reservation("insufficient")
        raise InsufficientWalletCredits("叙点不足，暂时无法发起本回合的模型调用。")
    hold = WalletHoldORM(
        id=new_id(),
        user_id=user_id,
        playthrough_id=playthrough_id,
        idempotency_key=idempotency_key,
        status="held",
        reserved_credits=policy.turn_reserve_credits,
        settled_credits=0,
        cost_microunits_per_credit=policy.cost_microunits_per_credit,
        expires_at=now + timedelta(minutes=policy.hold_minutes),
        hold_metadata={
            "policy": policy.public_view(),
            "available_before": available,
            # It is still the same short-lived wallet reservation, but the
            # ledger needs to say whether the player paid for an opening or a
            # later turn.  Never infer that from narrative text or request
            # data, which would make the financial record ambiguous.
            "reservation_kind": reservation_kind,
        },
    )
    uow.session.add(hold)
    await uow.commit()
    commerce_metrics.reservation("held")
    return TurnReservation(
        hold_id=hold.id,
        user_id=user_id,
        idempotency_key=idempotency_key,
        reserved_credits=hold.reserved_credits,
        cost_microunits_per_credit=hold.cost_microunits_per_credit,
    )


async def settle_turn_credits(
    uow: SqlUnitOfWork,
    reservation: TurnReservation | None,
    *,
    billable_cost_microunits: int,
    action_completed: bool,
) -> int:
    """Settle a held maximum into one append-only usage debit.

    A failed or degraded action releases its hold.  If a provider's actual
    billable cost unexpectedly exceeds the disclosed maximum, the player pays
    only the reserved maximum and the event is exposed as a capped settlement
    metric for operations to investigate.
    """

    if reservation is None:
        return 0
    user = await uow.session.scalar(
        sa.select(UserORM).where(UserORM.id == reservation.user_id).with_for_update()
    )
    if user is None:
        return 0
    hold = await uow.session.scalar(
        sa.select(WalletHoldORM)
        .where(WalletHoldORM.id == reservation.hold_id)
        .with_for_update()
    )
    if hold is None or hold.status in {"settled", "released", "capped"}:
        return int(hold.settled_credits) if hold is not None else 0
    requested = (
        ceil(max(0, billable_cost_microunits) / hold.cost_microunits_per_credit)
        if action_completed
        else 0
    )
    charge = min(requested, hold.reserved_credits)
    capped = requested > hold.reserved_credits
    if charge:
        reservation_kind = str((hold.hold_metadata or {}).get("reservation_kind", "turn"))
        entry = WalletLedgerORM(
            id=new_id(),
            user_id=reservation.user_id,
            credit_delta=-charge,
            entry_type="usage",
            source_type={
                "opening": "playthrough_opening",
                "creator": "creator_generation",
            }.get(reservation_kind, "playthrough_turn"),
            source_id=hold.id,
            idempotency_key=f"usage:{hold.id}",
            actor_id=None,
            reason="平台托管模型回合结算",
            entry_metadata={
                "billable_cost_microunits": max(0, billable_cost_microunits),
                "requested_credits": requested,
                "reserved_credits": hold.reserved_credits,
                "playthrough_id": hold.playthrough_id,
                "reservation_kind": reservation_kind,
            },
        )
        uow.session.add(entry)
        hold.wallet_ledger_id = entry.id
    hold.settled_credits = charge
    hold.status = "capped" if capped else ("settled" if charge else "released")
    hold.hold_metadata = {
        **dict(hold.hold_metadata or {}),
        "billable_cost_microunits": max(0, billable_cost_microunits),
        "requested_credits": requested,
        "settled_credits": charge,
        "release_reason": "action_not_completed" if not action_completed else "",
    }
    await uow.commit()
    commerce_metrics.settlement("capped" if capped else ("settled" if charge else "released"), charge)
    return charge
