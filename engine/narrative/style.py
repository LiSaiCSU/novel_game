"""Narrative style and AI-flavour control (Prompt section 56).

Two mechanisms:

* a rolling frequency table of the stock phrases this genre is prone to, fed
  back into the prompt as an avoid-list;
* a post-check that flags entities the prose invented but the world never
  approved.

Neither can change what happened - they only affect wording and telemetry.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field

from engine.contentpack.pack import ContentPack
from engine.orchestrator.turn import (
    DEFAULT_NARRATIVE_CHARS,
    MAX_NARRATIVE_CHARS,
    MIN_NARRATIVE_CHARS,
)

# A run of 2-4 CJK characters: the shape a proper noun usually takes.
# Built from code points so the engine source itself carries no world text.
_NAME_CANDIDATE = re.compile(f"[{chr(0x4E00)}-{chr(0x9FFF)}]{{2,4}}")


@dataclass(slots=True)
class StyleReport:
    overused: list[str] = field(default_factory=list)
    unknown_entities: list[str] = field(default_factory=list)
    length: int = 0
    needs_rewrite: bool = False


class NarrativeStyle:
    def __init__(self, pack: ContentPack) -> None:
        style = pack.narrative_style
        self.pack = pack
        self.language = str(style.get("language", ""))
        self.person = str(style.get("person", ""))
        self.tense = str(style.get("tense", ""))
        self.tone = str(style.get("tone", ""))
        self.target_length = int(style.get("target_length", 300))
        self.banned: list[str] = list(style.get("avoid_phrases", []) or [])
        self.window = int(style.get("phrase_repeat_window", 12))
        self.threshold = int(style.get("phrase_repeat_threshold", 2))
        self.guidance: list[str] = list(style.get("guidance", []) or [])
        self._recent: deque[str] = deque(maxlen=self.window)

    # ------------------------------------------------------------------
    def observe(self, text: str) -> None:
        """Remember what the last few paragraphs actually said."""
        if text:
            self._recent.append(text)

    def overused_phrases(self) -> list[str]:
        """Banned phrases plus anything the recent output keeps reaching for."""
        counts: dict[str, int] = {}
        for paragraph in self._recent:
            for phrase in self.banned:
                if phrase and phrase in paragraph:
                    counts[phrase] = counts.get(phrase, 0) + 1
        repeated = [p for p, n in counts.items() if n >= self.threshold]
        # Always suppress the pack's list; append anything trending on top.
        ordered = list(dict.fromkeys(self.banned + repeated))
        return ordered

    def avoid_list(self) -> str:
        phrases = self.overused_phrases()
        return "\n".join(f"- {p}" for p in phrases) if phrases else "-"

    # ------------------------------------------------------------------
    def review(self, text: str, known_entities: set[str]) -> StyleReport:
        """Post-generation check. Advisory: it reports, it does not rewrite state."""
        report = StyleReport(length=len(text))
        for phrase in self.banned:
            if phrase and phrase in text:
                report.overused.append(phrase)

        # Any 2-4 character run that looks like a proper noun but matches no
        # known entity is a candidate hallucination worth surfacing in debug.
        vocabulary = {e for e in known_entities if e}
        suspects: set[str] = set()
        for candidate in _NAME_CANDIDATE.findall(text):
            if candidate in vocabulary:
                continue
            if any(candidate in entity or entity in candidate for entity in vocabulary):
                continue
            suspects.add(candidate)
        # Only flag names that recur - single occurrences are usually ordinary prose.
        report.unknown_entities = sorted(
            s for s in suspects if text.count(s) >= 2 and len(s) >= 3
        )
        report.needs_rewrite = len(report.overused) >= 2
        return report

    def as_prompt_vars(self, max_chars: int | None = None) -> dict[str, str]:
        ceiling = max(
            MIN_NARRATIVE_CHARS,
            min(MAX_NARRATIVE_CHARS, int(max_chars or self.target_length)),
        )
        # Aim a little below the hard ceiling so the model has room to finish
        # a sentence and append the machine-readable BEAT block.
        target = max(MIN_NARRATIVE_CHARS, min(ceiling, int(ceiling * 0.85)))
        return {
            "language": self.language,
            "person": self.person,
            "tense": self.tense,
            "tone": self.tone,
            "target_length": str(target),
            "max_length": str(ceiling),
            "avoid_phrases": self.avoid_list(),
        }

    @staticmethod
    def output_token_budget(max_chars: int, declared: int | None) -> int:
        """Translate a Chinese-character ceiling into a conservative token cap."""
        ceiling = max(MIN_NARRATIVE_CHARS, min(MAX_NARRATIVE_CHARS, int(max_chars)))
        calculated = max(900, int(ceiling * 1.4) + 400)
        return min(calculated, declared) if declared else calculated

    @staticmethod
    def enforce_max_chars(text: str, max_chars: int) -> str:
        """Keep generated prose under the user ceiling at a natural boundary."""
        ceiling = max(
            MIN_NARRATIVE_CHARS,
            min(MAX_NARRATIVE_CHARS, int(max_chars or DEFAULT_NARRATIVE_CHARS)),
        )
        if len(text) <= ceiling:
            return text.strip()
        clipped = text[:ceiling]
        # Streaming callers retain this much tail, so choosing a boundary in
        # this window never requires retracting text already shown to a reader.
        floor = max(0, ceiling - 180)
        boundary = max(clipped.rfind(mark) for mark in ("。", "！", "？", "\n"))
        if boundary >= floor:
            clipped = clipped[: boundary + 1]
        return clipped.rstrip()
