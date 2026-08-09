"""Deterministic intent parser.

Used when no LLM is configured, when the model times out, or when its output
fails validation (DECISIONS D-007). It is intentionally dumb: keyword and
entity matching driven entirely by the content pack's vocabulary table, so it
carries no genre knowledge of its own.

It is also the reason the whole world engine can be tested without a model.
"""

from __future__ import annotations

import re
from typing import Any

from engine.actions.schema import ActionGoal, PlayerIntent
from engine.contentpack.pack import ContentPack
from engine.core.types import ActionType, RequestSize
from engine.world.state_view import WorldStateView


class FallbackIntentParser:
    def __init__(self, pack: ContentPack) -> None:
        self.pack = pack
        vocab = pack.vocabulary
        self._action_aliases: dict[str, list[str]] = vocab.get("action_aliases", {}) or {}
        self._method_aliases: dict[str, list[str]] = vocab.get("method_aliases", {}) or {}
        self._query_aliases: dict[str, list[str]] = vocab.get("query_aliases", {}) or {}
        self._time_words: dict[str, int] = vocab.get("time_words", {}) or {}
        self._time_units: dict[str, int] = vocab.get("time_units", {}) or {}
        self._size_hints: dict[str, list[str]] = vocab.get("request_size_hints", {}) or {}
        self._refusals: list[str] = vocab.get("refusal_words", []) or []

    # ------------------------------------------------------------------
    def parse(self, text: str, state: WorldStateView) -> PlayerIntent:
        raw = (text or "").strip()
        intent = PlayerIntent(raw_text=raw, actor_id=state.player.id)
        if not raw:
            intent.action_type = ActionType.CUSTOM
            intent.confidence = 0.0
            intent.ambiguity = "empty_input"
            return intent

        query = self._match_query(raw)
        if query is not None:
            intent.action_type = query
            intent.confidence = 0.95
            return intent

        target = self._match_character(raw, state)
        if target is not None:
            intent.target_id = target[0]
            intent.target_key = target[1]

        location_key = self._match_location(raw, state)
        if location_key:
            intent.location_key = location_key

        item_key = self._match_item(raw, state)
        if item_key:
            intent.item_key = item_key

        skill_key = self._match_skill(raw, state)
        if skill_key:
            intent.skill_key = skill_key

        duration = self._match_duration(raw)
        if duration:
            intent.duration_minutes = duration

        method = self._match_method(raw)
        if method:
            intent.method = method

        action_type, score = self._match_action(raw)
        intent.action_type = action_type
        intent.confidence = score

        # Disambiguate a few overlaps the keyword table cannot settle alone.
        if action_type is ActionType.MOVE and not location_key:
            intent.action_type = ActionType.CUSTOM
            intent.confidence = min(intent.confidence, 0.4)
            intent.ambiguity = "move_target_unknown"
        if action_type in (ActionType.TALK, ActionType.ASK) and intent.target_id is None:
            intent.confidence = min(intent.confidence, 0.4)
            intent.ambiguity = "conversation_target_unknown"
        if action_type is ActionType.USE_SKILL and not skill_key:
            intent.confidence = min(intent.confidence, 0.4)
            intent.ambiguity = "skill_unknown"
        if action_type in (ActionType.USE_ITEM, ActionType.DROP, ActionType.GIVE_ITEM) and not item_key:
            intent.confidence = min(intent.confidence, 0.4)
            intent.ambiguity = "item_unknown"

        intent.request_size = self._match_request_size(raw)
        intent.goal = self._infer_goal(intent, raw)
        if intent.action_type in (ActionType.TALK, ActionType.ASK, ActionType.CONVERSATION):
            intent.utterance = raw
        if any(word in raw for word in self._refusals) and intent.action_type is ActionType.CUSTOM:
            intent.action_type = ActionType.REJECT_QUEST
            intent.confidence = 0.5
        return intent

    # ------------------------------------------------------------------
    def _match_query(self, text: str) -> ActionType | None:
        best: tuple[ActionType, int] | None = None
        for name, aliases in self._query_aliases.items():
            for alias in aliases:
                if alias and alias in text and (best is None or len(alias) > best[1]):
                    try:
                        best = (ActionType(name), len(alias))
                    except ValueError:
                        continue
        return best[0] if best else None

    def _match_action(self, text: str) -> tuple[ActionType, float]:
        best_type = ActionType.CUSTOM
        best_len = 0
        for name, aliases in self._action_aliases.items():
            try:
                candidate = ActionType(name)
            except ValueError:
                continue
            for alias in aliases:
                if alias and alias in text and len(alias) > best_len:
                    best_type, best_len = candidate, len(alias)
        if best_len == 0:
            return ActionType.CUSTOM, 0.35
        # longer keyword match -> more confident, capped well below an LLM's
        return best_type, min(0.9, 0.55 + 0.1 * best_len)

    def _match_method(self, text: str) -> str | None:
        best: tuple[str, int] | None = None
        for method, aliases in self._method_aliases.items():
            for alias in aliases:
                if alias and alias in text and (best is None or len(alias) > best[1]):
                    best = (method, len(alias))
        return best[0] if best else None

    def _match_character(self, text: str, state: WorldStateView) -> tuple[str, str] | None:
        best: tuple[str, str, int] | None = None
        for ch in state.present_characters:
            for label in filter(None, (ch.name, ch.title, ch.display_name)):
                if label in text and (best is None or len(label) > best[2]):
                    best = (ch.id, ch.key, len(label))
        return (best[0], best[1]) if best else None

    def _match_location(self, text: str, state: WorldStateView) -> str | None:
        best: tuple[str, int] | None = None
        current = state.location_key()
        for loc in state.graph.all():
            if loc.key == current:
                continue
            if loc.name and loc.name in text and (best is None or len(loc.name) > best[1]):
                best = (loc.key, len(loc.name))
        return best[0] if best else None

    def _match_item(self, text: str, state: WorldStateView) -> str | None:
        best: tuple[str, int] | None = None
        owned = {row.item_key for row in state.inventory}
        for item in self.pack.items:
            name = str(item.get("name", ""))
            key = str(item.get("key", ""))
            if not name or name not in text:
                continue
            # prefer something the player actually has
            weight = len(name) + (100 if key in owned else 0)
            if best is None or weight > best[1]:
                best = (key, weight)
        return best[0] if best else None

    def _match_skill(self, text: str, state: WorldStateView) -> str | None:
        best: tuple[str, int] | None = None
        known = {row.skill_key for row in state.known_skills}
        for skill in self.pack.skills:
            name = str(skill.get("name", ""))
            key = str(skill.get("key", ""))
            if not name or name not in text:
                continue
            weight = len(name) + (100 if key in known else 0)
            if best is None or weight > best[1]:
                best = (key, weight)
        return best[0] if best else None

    def _match_duration(self, text: str) -> int | None:
        # Spelled-out spans first ("half an hour"), longest match wins.
        for word, minutes in sorted(self._time_words.items(), key=lambda kv: -len(kv[0])):
            if word in text:
                return int(minutes)
        # Then "<number><unit>", again longest unit first so "个月" beats "月".
        for unit, minutes in sorted(self._time_units.items(), key=lambda kv: -len(kv[0])):
            match = re.search(rf"(\d+)\s*{re.escape(unit)}", text)
            if match:
                return int(match.group(1)) * int(minutes)
        return None

    def _match_request_size(self, text: str) -> RequestSize:
        for size in ("extreme", "large", "moderate", "small"):
            for hint in self._size_hints.get(size, []):
                if hint and hint in text:
                    return RequestSize(size)
        return RequestSize.TRIVIAL

    def _infer_goal(self, intent: PlayerIntent, text: str) -> ActionGoal:
        mapping: dict[ActionType, str] = {
            ActionType.ASK: "obtain_information",
            ActionType.OBSERVE: "explore",
            ActionType.SEARCH: "explore",
            ActionType.MOVE: "reach_location",
            ActionType.CULTIVATE: "improve_self",
            ActionType.BREAKTHROUGH: "improve_self",
            ActionType.ATTACK: "harm",
            ActionType.DEFEND: "protect",
            ActionType.HIDE: "escape",
            ActionType.BUY: "trade",
            ActionType.SELL: "trade",
            ActionType.STEAL: "obtain_item",
            ActionType.PICKUP: "obtain_item",
            ActionType.TALK: "change_relationship",
            ActionType.CONVERSATION: "change_relationship",
            ActionType.ACCEPT_QUEST: "complete_quest",
        }
        goal_type = mapping.get(intent.action_type, "other")
        payload: dict[str, Any] = {"type": goal_type}
        if intent.item_key:
            payload["item_key"] = intent.item_key
        if goal_type == "obtain_information":
            payload["topic"] = text[:80]
        return ActionGoal(**payload)
