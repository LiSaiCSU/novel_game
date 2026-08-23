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
from difflib import SequenceMatcher

from engine.contentpack.pack import ContentPack
from engine.orchestrator.turn import (
    DEFAULT_NARRATIVE_CHARS,
    MAX_NARRATIVE_CHARS,
    MIN_NARRATIVE_CHARS,
)

# A run of 2-4 CJK characters: the shape a proper noun usually takes.
# Built from code points so the engine source itself carries no world text.
_NAME_CANDIDATE = re.compile(f"[{chr(0x4E00)}-{chr(0x9FFF)}]{{2,4}}")
#: A maximal run of one script, delimited by anything else. Only a run
#: short enough to be a name is treated as a name candidate.
_CJK_RUN = re.compile(f"[{chr(0x4E00)}-{chr(0x9FFF)}]+")
_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n")
_PROSE_SPACE = re.compile(r"\s+")

#: Sentence terminators, plus the closing marks that trail them.
_SENTENCE_END = "。！？!?…"
_SENTENCE_CLOSERS = "”’」』）)》〉】"

#: A recap sentence is long. Short lines - "他没答应。", a repeated line of
#: dialogue, a deliberate callback - are how prose actually refers back to
#: itself, so removing them would damage the writing rather than repair it.
MIN_SENTENCE_ECHO_CHARS = 30
SENTENCE_ECHO_RATIO = 0.90


def _comparable_prose(text: str) -> str:
    return _PROSE_SPACE.sub("", text).strip()


def split_sentences(paragraph: str) -> list[str]:
    """Cut a paragraph after each terminator, keeping the punctuation.

    The trailing element has no terminator when the paragraph is still being
    written; callers streaming a response use that to tell a finished sentence
    from one the model is halfway through.
    """
    sentences: list[str] = []
    start = 0
    index = 0
    while index < len(paragraph):
        if paragraph[index] in _SENTENCE_END:
            end = index + 1
            while end < len(paragraph) and paragraph[end] in _SENTENCE_END + _SENTENCE_CLOSERS:
                end += 1
            sentences.append(paragraph[start:end])
            start = end
            index = end
        else:
            index += 1
    if start < len(paragraph):
        sentences.append(paragraph[start:])
    return sentences


def _is_complete_sentence(sentence: str) -> bool:
    stripped = sentence.rstrip(_SENTENCE_CLOSERS)
    return bool(stripped) and stripped[-1] in _SENTENCE_END


def _is_repeated_sentence(candidate: str, known: list[str]) -> bool:
    """Whether one sentence merely restates a sentence already told.

    Paragraph-level filtering only catches a wholesale paste.  The far more
    common failure is a new paragraph that re-narrates two or three sentences
    of what the reader just read before adding anything - which is what makes
    a chapter feel like it is treading water.
    """
    if len(candidate) < MIN_SENTENCE_ECHO_CHARS:
        return False
    for sentence in known:
        if len(sentence) < MIN_SENTENCE_ECHO_CHARS:
            continue
        if candidate in sentence or sentence in candidate:
            return True
        if (
            SequenceMatcher(None, candidate, sentence, autojunk=False).ratio()
            >= SENTENCE_ECHO_RATIO
        ):
            return True
    return False


def _known_sentences(paragraphs: list[str]) -> list[str]:
    return [
        comparable
        for paragraph in paragraphs
        for sentence in split_sentences(paragraph)
        if (comparable := _comparable_prose(sentence))
    ]


def repeated_opening_length(text: str, recent_narrative: str, *, final: bool = False) -> int:
    """Return the leading source length that merely repeats recent prose.

    Some compatible model endpoints occasionally begin a continuation by
    copying one or more paragraphs supplied as context.  The prompt says not
    to do that, but presentation correctness cannot depend on compliance.
    Only substantial, near-verbatim *leading* paragraphs are removed; short
    dialogue callbacks and intentional echoes remain untouched.

    While a response is streaming, an unfinished possible duplicate is held
    until its paragraph boundary arrives.  Returning ``-1`` tells the caller
    that it does not yet have enough text to make a stable decision.
    """

    if not text or not recent_narrative:
        return 0
    recent = [
        _comparable_prose(paragraph)
        for paragraph in _PARAGRAPH_BREAK.split(recent_narrative)
        if _comparable_prose(paragraph)
    ]
    recent_joined = _comparable_prose(recent_narrative)
    if not recent:
        return 0

    offset = 0
    while offset < len(text):
        remainder = text[offset:].lstrip()
        offset += len(text[offset:]) - len(remainder)
        boundary = _PARAGRAPH_BREAK.search(remainder)
        if boundary is None:
            candidate = _comparable_prose(remainder)
            if not final:
                if len(candidate) < 64:
                    return -1
                possible_repeat = candidate in recent_joined or any(
                    SequenceMatcher(
                        None,
                        candidate,
                        paragraph[: len(candidate)],
                        autojunk=False,
                    ).ratio()
                    >= 0.9
                    for paragraph in recent
                    if len(paragraph) >= len(candidate)
                )
                if possible_repeat:
                    return -1
                return offset
            if final and _is_repeated_paragraph(candidate, recent):
                return len(text)
            return offset

        candidate = _comparable_prose(remainder[: boundary.start()])
        if not _is_repeated_paragraph(candidate, recent):
            return offset
        offset += boundary.end()
    return offset


def _is_repeated_paragraph(candidate: str, recent: list[str]) -> bool:
    """Whether a paragraph adds nothing that has not already been told.

    Deliberately not symmetric.  A candidate contained in known prose is a
    pure copy.  A candidate that *contains* known prose is a copy plus
    something new, and belongs to the sentence filter - dropping it whole
    would throw the new material away with the echo.
    """
    if len(candidate) < 36:
        return False
    for paragraph in recent:
        if candidate == paragraph or candidate in paragraph:
            return True
        if (
            min(len(candidate), len(paragraph)) >= 48
            and SequenceMatcher(None, candidate, paragraph, autojunk=False).ratio() >= 0.94
        ):
            return True
    return False


def _could_be_repeated_paragraph(candidate: str, known: list[str]) -> bool:
    """Whether an unfinished paragraph still looks copied from known prose."""

    if not candidate:
        return False
    return candidate in "".join(known) or any(
        len(paragraph) >= len(candidate)
        and SequenceMatcher(
            None,
            candidate,
            paragraph[: len(candidate)],
            autojunk=False,
        ).ratio()
        >= 0.9
        for paragraph in known
    )


def _keep_fresh_sentences(
    paragraph: str, known_sentences: list[str], *, complete_only: bool
) -> tuple[str, list[str]]:
    """Drop the sentences of one paragraph that merely retell known prose.

    Returns the surviving text and the comparable form of what survived, so
    the caller can hold later paragraphs against it too.  When
    ``complete_only`` is set the still-unfinished trailing sentence is
    withheld: a half-written sentence cannot be judged, and a streaming caller
    must never show text it might want back.
    """
    kept: list[str] = []
    accepted: list[str] = []
    for sentence in split_sentences(paragraph):
        if complete_only and not _is_complete_sentence(sentence):
            break
        comparable = _comparable_prose(sentence)
        if not comparable:
            kept.append(sentence)
            continue
        if _is_repeated_sentence(comparable, [*known_sentences, *accepted]):
            continue
        kept.append(sentence)
        accepted.append(comparable)
    return "".join(kept).strip(), accepted


def filter_repeated_paragraphs(
    text: str,
    recent_narrative: str,
    *,
    final: bool = True,
) -> str:
    """Remove copied prose without breaking streaming monotonicity.

    Three things get removed: a paragraph pasted from recent narrative, a
    paragraph the response already used once, and individual long sentences
    that restate something the reader has just been told.  The last of these
    is the common case - a chapter that opens by summarising the previous one
    before it gets to anything new.

    While streaming, a new paragraph is held until it has 64 comparable
    characters that cannot be a copy, and only its finished sentences are
    exposed.  Because nothing is shown while it might still be a duplicate,
    later calls only ever extend the visible string.
    """

    if not text:
        return ""
    known = [
        _comparable_prose(paragraph)
        for paragraph in _PARAGRAPH_BREAK.split(recent_narrative)
        if _comparable_prose(paragraph)
    ]
    known_sentences = _known_sentences(
        [paragraph for paragraph in _PARAGRAPH_BREAK.split(recent_narrative) if paragraph.strip()]
    )
    accepted: list[str] = []
    accepted_known: list[str] = []
    accepted_sentences: list[str] = []
    start = 0
    boundaries = list(_PARAGRAPH_BREAK.finditer(text))

    def take(paragraph: str, *, complete_only: bool) -> None:
        seen_paragraphs = [*known, *accepted_known]
        if _is_repeated_paragraph(_comparable_prose(paragraph), seen_paragraphs):
            return
        # Whatever survives that is a copy plus new material, so the echo is
        # removed sentence by sentence rather than by discarding the lot.
        kept, fresh = _keep_fresh_sentences(
            paragraph, [*known_sentences, *accepted_sentences], complete_only=complete_only
        )
        if not kept:
            return
        comparable = _comparable_prose(kept)
        if _is_repeated_paragraph(comparable, seen_paragraphs):
            return
        accepted.append(kept)
        accepted_known.append(comparable)
        accepted_sentences.extend(fresh)

    for boundary in boundaries:
        paragraph = text[start : boundary.start()].strip()
        if paragraph:
            take(paragraph, complete_only=False)
        start = boundary.end()

    remainder = text[start:].strip()
    if remainder:
        if final:
            take(remainder, complete_only=False)
        elif len(_comparable_prose(remainder)) >= 64 and not _could_be_repeated_paragraph(
            _comparable_prose(remainder), [*known, *accepted_known]
        ):
            take(remainder, complete_only=True)

    return "\n\n".join(accepted).strip()


def strip_repeated_opening(text: str, recent_narrative: str) -> str:
    """Backward-compatible name for full continuation de-duplication."""

    return filter_repeated_paragraphs(text, recent_narrative, final=True)


#: Quotation marks that must be balanced for prose to read as finished. Only
#: paired marks are listed: a straight quote is ambiguous and is left alone.
_QUOTE_PAIRS: tuple[tuple[str, str], ...] = (
    (chr(0x201C), chr(0x201D)),
    (chr(0x2018), chr(0x2019)),
    (chr(0x300C), chr(0x300D)),
    (chr(0x300E), chr(0x300F)),
)


def quotations_balanced(text: str) -> bool:
    """Whether every quotation opened in ``text`` was also closed."""
    return all(text.count(opener) == text.count(closer) for opener, closer in _QUOTE_PAIRS)


def _sentence_end_offsets(text: str) -> list[int]:
    """Offsets just past every complete sentence in ``text``."""
    offsets: list[int] = []
    index = 0
    while index < len(text):
        if text[index] in _SENTENCE_END:
            end = index + 1
            while end < len(text) and text[end] in _SENTENCE_END + _SENTENCE_CLOSERS:
                end += 1
            offsets.append(end)
            index = end
        else:
            index += 1
    return offsets


def drop_unfinished_tail(text: str) -> str:
    """Remove a trailing half-written sentence left by a truncated response.

    A model that runs out of output budget stops wherever it happens to be and
    the reader is handed a scene that ends mid-word. The honest repair is to
    end on the last sentence that actually finished - and, if that sentence
    left a quotation hanging, on the last one that did not.
    """
    stripped = text.rstrip()
    if not stripped:
        return ""
    offsets = _sentence_end_offsets(stripped)
    if not offsets:
        return stripped
    if offsets[-1] == len(stripped) and quotations_balanced(stripped):
        return stripped
    for offset in reversed(offsets):
        if quotations_balanced(stripped[:offset]):
            return stripped[:offset].rstrip()
    return stripped


def _standalone_runs(text: str) -> set[str]:
    """Name-length runs that appear delimited at least once in ``text``.

    A run wedged between other characters of the same script is a slice of a
    sentence, not a name. One that stands alone between punctuation marks is
    at least plausibly one.
    """
    runs: set[str] = set()
    for match in _CJK_RUN.finditer(text):
        run = match.group(0)
        if len(run) <= 4:
            runs.add(run)
            continue
        # A name normally opens the clause it belongs to, so the delimited
        # start of a run is a plausible name; the middle of one is prose.
        for width in (2, 3, 4):
            runs.add(run[:width])
    return runs


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

        # A short run that looks like a proper noun but matches no known entity
        # is a candidate hallucination worth surfacing in debug. Sliding a
        # fixed-width window over continuous prose, however, mostly produces
        # slices of ordinary sentences, which buried the real finds under
        # dozens of fragments. A name has to stand as a whole token at least
        # once - bounded by punctuation, a quotation mark, or a line break.
        vocabulary = {e for e in known_entities if e}
        suspects: set[str] = set()
        for candidate in _standalone_runs(text):
            if len(candidate) < 3:
                continue
            if candidate in vocabulary:
                continue
            if any(candidate in entity or entity in candidate for entity in vocabulary):
                continue
            suspects.add(candidate)
        # Only flag names that recur - single occurrences are usually ordinary prose.
        report.unknown_entities = sorted(s for s in suspects if text.count(s) >= 2)
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
            "style_guidance": (
                "\n".join(f"- {item}" for item in self.guidance) if self.guidance else "-"
            ),
        }

    @staticmethod
    def output_token_budget(max_chars: int, declared: int | None) -> int:
        """Translate a Chinese-character ceiling into a conservative token cap."""
        ceiling = max(MIN_NARRATIVE_CHARS, min(MAX_NARRATIVE_CHARS, int(max_chars)))
        calculated = max(900, int(ceiling * 1.4) + 400)
        return min(calculated, declared) if declared else calculated

    @staticmethod
    def enforce_max_chars(text: str, max_chars: int) -> str:
        """Keep generated prose under the user ceiling at a natural boundary.

        A ceiling that lands mid-scene is unavoidable, but *where* it lands is
        not. Cutting at the nearest full stop routinely severed a line of
        dialogue from its closing quotation mark, so the last thing the reader
        saw was an unterminated speech. Preference order is therefore: a
        paragraph break, then a sentence end that leaves every quotation
        closed, then - only if neither exists in the window - the raw ceiling.
        """
        ceiling = max(
            MIN_NARRATIVE_CHARS,
            min(MAX_NARRATIVE_CHARS, int(max_chars or DEFAULT_NARRATIVE_CHARS)),
        )
        if len(text) <= ceiling:
            return drop_unfinished_tail(text.strip())
        clipped = text[:ceiling]
        # Streaming callers retain this much tail, so choosing a boundary in
        # this window never requires retracting text already shown to a reader.
        floor = max(0, ceiling - 180)

        paragraph = clipped.rfind(chr(10) + chr(10))
        if paragraph >= floor and quotations_balanced(clipped[:paragraph]):
            return clipped[:paragraph].rstrip()

        for offset in reversed(_sentence_end_offsets(clipped)):
            if offset < floor:
                break
            if quotations_balanced(clipped[:offset]):
                return clipped[:offset].rstrip()
        return clipped.rstrip()
