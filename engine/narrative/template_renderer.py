"""Deterministic narrative renderer.

Used when no model is configured or generation fails. It reports the facts
plainly rather than pretending to be literature - a degraded turn should read
as terse, never as invented.

All wording comes from the content pack's narrative templates, so the engine
stays genre-free.
"""

from __future__ import annotations

from typing import Any

from engine.actions.schema import ActionOutcome
from engine.contentpack.pack import ContentPack
from engine.core.models import Character
from engine.world.clock import WorldClock
from engine.world.state_view import WorldStateView


class TemplateNarrativeRenderer:
    def __init__(self, pack: ContentPack) -> None:
        self.pack = pack
        self.t: dict[str, Any] = pack.narrative_templates or {}

    # ------------------------------------------------------------------
    def render(
        self,
        state: WorldStateView,
        outcome: ActionOutcome,
        *,
        npc_lines: list[str] | None = None,
        world_lines: list[str] | None = None,
        degraded_notice: bool = False,
    ) -> str:
        parts: list[str] = []
        if outcome.summary_key == "rejected":
            parts.append(self._rejection(outcome))
        elif outcome.summary_key.startswith("query_"):
            parts.append(self._query(state, outcome.summary_key.removeprefix("query_")))
        else:
            parts.append(self._action(state, outcome))

        parts += [line for line in (npc_lines or []) if line]
        if world_lines:
            prefix = self._get("world_event.prefix", "")
            parts += [f"{prefix}{line}" for line in world_lines if line]
        if degraded_notice:
            notice = self._get("labels.degraded_notice", "")
            if notice:
                parts.append(notice)
        return "\n\n".join(p for p in parts if p)

    # ------------------------------------------------------------------
    def _rejection(self, outcome: ActionOutcome) -> str:
        code = str(outcome.facts.get("reason_code", ""))
        by_code = self._get("rejection.by_reason_code", {}) or {}
        body = by_code.get(code) or self._get("rejection.default", "")
        header = self._get("rejection.header", "")
        return f"{header}{body}" if header else body

    def _action(self, state: WorldStateView, outcome: ActionOutcome) -> str:
        templates = self._get("action", {}) or {}
        template = templates.get(outcome.summary_key) or templates.get("DEFAULT", "")
        fields = self._fields(state, outcome)
        return _safe_format(template, fields)

    def _fields(self, state: WorldStateView, outcome: ActionOutcome) -> dict[str, str]:
        clock = state.clock
        facts = outcome.facts
        notes = self._get("notes", {}) or {}
        fields: dict[str, str] = {
            key: _stringify(value)
            for key, value in facts.items()
            if isinstance(value, (str, int, float, bool))
        }
        fields.setdefault("location", state.location.name if state.location else "")
        fields.setdefault("duration_label", self._duration(clock, outcome.time_cost_minutes))
        fields["minutes_label"] = self._duration(clock, int(facts.get("minutes", outcome.time_cost_minutes)))
        fields["travel_note"] = _safe_format(notes.get("travel", ""), fields)

        if outcome.summary_key == "CULTIVATE":
            gain = float(facts.get("gain", 0.0))
            key = "cultivation_progress" if gain >= 0.005 else "cultivation_no_progress"
            fields["progress_note"] = _safe_format(
                notes.get(key, ""), {**fields, "progress": f"{gain * 100:.1f}%"}
            )
        if outcome.summary_key == "ATTACK_HIT":
            note_key = "damage_lethal" if facts.get("killed") else "damage"
            fields["damage_note"] = _safe_format(notes.get(note_key, ""), fields)
        if outcome.summary_key == "BREAKTHROUGH_FAILED":
            fields["injury_note"] = notes.get("injury", "")
        if outcome.summary_key == "REST":
            fields["recovery_note"] = notes.get("recovery", "")
        if outcome.summary_key in ("USE_ITEM", "USE_SKILL"):
            fields.setdefault("effect_note", notes.get("effect_none", ""))
        if outcome.summary_key == "SEARCH":
            found = self._get("action.PICKUP", "")
            fields["search_result"] = _safe_format(found, fields)
        if outcome.summary_key == "OBSERVE":
            present = [c.display_name for c in state.present_characters if c.alive]
            if present:
                prefix = self._get("labels.present_prefix", "")
                separator = self._get("labels.list_separator", ", ")
                fields["observation"] = prefix + separator.join(present)
            else:
                fields["observation"] = self._get("labels.nobody_here", "")
        return fields

    def _duration(self, clock: WorldClock, minutes: int) -> str:
        unit, count = clock.duration_parts(minutes)
        template = (self._get("duration", {}) or {}).get(unit, "")
        return _safe_format(template, {"n": str(count)})

    # ------------------------------------------------------------------
    def npc_line(self, npc: Character, speech_intent: str, spoken: str | None) -> str:
        table = self._get("npc", {}) or {}
        if spoken:
            return _safe_format(table.get("speaks", ""), {"name": npc.display_name, "line": spoken})
        mapping = {
            "refuse": "refuses",
            "deny_unknown": "refuses",
            "comply": "default",
            "deflect": "silent",
            "neutral": "default",
        }
        key = mapping.get(speech_intent, "default")
        return _safe_format(
            table.get(key, table.get("default", "")),
            {"name": npc.display_name, "action_label": speech_intent},
        )

    # ------------------------------------------------------------------
    def query(self, state: WorldStateView, kind: str) -> str:
        return self._query(state, kind)

    def _query(self, state: WorldStateView, kind: str) -> str:
        q = self._get("query", {}) or {}
        ladder = self.pack.realms
        if kind == "status":
            player = state.player
            lines = [
                q.get("status_header", ""),
                f"{player.name} / {ladder.display(player.realm, player.realm_stage)}",
                f"HP {player.health}/{player.max_health}",
                f"MP {player.spiritual_power}/{player.max_spiritual_power}",
                f"{ladder.progression_name} {player.cultivation_progress * 100:.1f}%",
                f"{state.time.label}",
                f"{state.location.name if state.location else ''}",
            ]
            return "\n".join(line for line in lines if line)
        if kind == "inventory":
            if not state.inventory:
                return f"{q.get('inventory_header', '')}\n{q.get('inventory_empty', '')}"
            rows = []
            for row in state.inventory:
                item = self.pack.item(row.item_key) or {}
                rows.append(f"{item.get('name', row.item_key)} x{row.quantity}")
            return "\n".join([q.get("inventory_header", ""), *rows])
        if kind == "relationships":
            if not state.relationships:
                return f"{q.get('relationships_header', '')}\n{q.get('relationships_empty', '')}"
            rows = []
            for other_id, rel in state.relationships.items():
                other = state.character_by_id(other_id)
                name = other.display_name if other else other_id
                dims = ", ".join(f"{k}={v}" for k, v in rel.as_dict().items() if v)
                rows.append(f"{name}: {dims or '-'}")
            return "\n".join([q.get("relationships_header", ""), *rows])
        if kind == "quests":
            active = [q_ for q_ in state.active_quests if str(q_.status) in ("offered", "active")]
            if not active:
                return f"{q.get('quests_header', '')}\n{q.get('quests_empty', '')}"
            rows = [f"{item.name} ({item.status})" for item in active]
            return "\n".join([q.get("quests_header", ""), *rows])
        return ""

    # ------------------------------------------------------------------
    def _get(self, dotted: str, default: Any = "") -> Any:
        node: Any = self.t
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node


def _safe_format(template: str, fields: dict[str, str]) -> str:
    """Format without exploding on a placeholder the facts happen not to carry."""
    if not template:
        return ""
    out = template
    for key, value in fields.items():
        out = out.replace("{" + key + "}", str(value))
    # drop any placeholders that were never supplied
    while "{" in out and "}" in out:
        start = out.find("{")
        end = out.find("}", start)
        if end == -1:
            break
        out = out[:start] + out[end + 1 :]
    return out.strip()


def _stringify(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else ""
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)
