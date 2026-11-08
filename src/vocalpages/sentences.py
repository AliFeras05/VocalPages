"""Regex-based sentence splitting and sentence positions in displayed text.

A boundary is a run of ``.``, ``!``, ``?`` or ``…`` (plus closing quotes or
brackets) followed by whitespace. A candidate boundary is rejected when:

- the next sentence would start with a lowercase letter or a digit
  (``"Hi!" she said``, ``wait... what``, ``No. 5``);
- the word before a single ``.`` is a known abbreviation (``Dr.``, ``e.g.``),
  a single initial (``J. Smith``) or a dotted acronym (``U.S.``).

Decimals such as ``3.14`` never match because a boundary needs whitespace after
the punctuation. Paragraph breaks always end a sentence, and sentences longer
than ``max_chars`` are cut at commas or word boundaries so the TTS gets
manageable chunks.
"""

from __future__ import annotations

import bisect
import re

MAX_SENTENCE_CHARS = 400

ABBREVIATIONS = frozenset(
    {
        "mr", "mrs", "ms", "mx", "dr", "prof", "sr", "jr", "st", "mt", "ft", "rev", "hon",
        "gen", "col", "capt", "lt", "sgt", "gov", "pres", "vs", "etc", "e.g", "i.e", "cf",
        "al", "fig", "figs", "no", "nos", "vol", "vols", "ch", "pp", "p", "ed", "eds",
        "approx", "est", "dept", "inc", "ltd", "co", "corp", "jan", "feb", "mar", "apr",
        "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec", "a.m", "p.m",
    }
)
# Abbreviations that often end a sentence: split after them if a capital follows.
SENTENCE_FINAL_ABBREVIATIONS = frozenset({"etc", "inc", "ltd", "co", "corp", "a.m", "p.m"})

_BOUNDARY_RE = re.compile(r"(?P<punct>[.!?…]+)(?P<close>[\"'”’»)\]]*)(?P<space>\s+)")
_ACRONYM_RE = re.compile(r"^(?:[A-Za-z]\.)+[A-Za-z]$")
_OPENING_RE = re.compile(r"[\"'“‘«(\[]*(.)")
_PARAGRAPH_RE = re.compile(r"\n\s*\n")


def _next_start_char(text: str, pos: int) -> str:
    match = _OPENING_RE.match(text, pos)
    return match.group(1) if match else ""


def _is_boundary(text: str, match: re.Match[str]) -> bool:
    nxt = _next_start_char(text, match.end())
    if not nxt or nxt.islower() or nxt.isdigit():
        return False
    punct = match.group("punct")
    if punct != ".":
        return True  # "!", "?", ellipsis or mixed runs end a sentence before a capital
    word = text[: match.start()].rsplit(None, 1)[-1] if text[: match.start()].strip() else ""
    word = word.lstrip("\"'“‘«([")
    key = word.lower()
    if key in ABBREVIATIONS:
        return key in SENTENCE_FINAL_ABBREVIATIONS
    if len(word) == 1 and word.isalpha() and word.isupper():
        return False  # an initial, as in "J. Smith"
    if _ACRONYM_RE.match(word):
        return False  # "U.S." or "Ph.D"
    return True


def _split_long(sentence: str, max_chars: int) -> list[str]:
    """Split an over-long sentence at word boundaries, preferring commas and semicolons."""
    parts: list[str] = []
    rest = sentence
    while len(rest) > max_chars:
        window = rest[:max_chars]
        cut = max(window.rfind(", "), window.rfind("; "))
        cut = cut + 1 if cut > max_chars // 3 else window.rfind(" ")
        if cut <= 0:
            cut = max_chars
        parts.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    if rest:
        parts.append(rest)
    return parts


def split_paragraph(paragraph: str) -> list[str]:
    """Split one paragraph (no blank lines) into sentences, without length limits."""
    text = " ".join(paragraph.split())
    sentences: list[str] = []
    start = 0
    for match in _BOUNDARY_RE.finditer(text):
        if _is_boundary(text, match):
            end = match.end() - len(match.group("space"))
            sentences.append(text[start:end])
            start = match.end()
    if start < len(text):
        sentences.append(text[start:])
    return [s for s in sentences if s.strip()]


def split_sentences(text: str, max_chars: int = MAX_SENTENCE_CHARS) -> list[str]:
    """Split text into sentences for reading aloud and highlighting.

    Every returned sentence appears verbatim, in order, in ``normalize_text(text)``.
    """
    sentences: list[str] = []
    for paragraph in _PARAGRAPH_RE.split(text):
        for sentence in split_paragraph(paragraph):
            sentences.extend(_split_long(sentence, max_chars))
    return sentences


def normalize_text(text: str) -> str:
    """Collapse whitespace inside paragraphs, keeping one blank line between them."""
    paragraphs = (" ".join(p.split()) for p in _PARAGRAPH_RE.split(text))
    return "\n\n".join(p for p in paragraphs if p)


def locate_sentences(display_text: str, sentences: list[str]) -> list[tuple[int, int]]:
    """Return the (start, end) character span of each sentence within ``display_text``.

    Sentences are searched in order; one that cannot be found gets an empty
    span at the current position.
    """
    spans: list[tuple[int, int]] = []
    pos = 0
    for sentence in sentences:
        start = display_text.find(sentence, pos)
        if start < 0:
            spans.append((pos, pos))
            continue
        end = start + len(sentence)
        spans.append((start, end))
        pos = end
    return spans


def sentence_at(spans: list[tuple[int, int]], position: int) -> int | None:
    """Return the index of the sentence whose span contains ``position``, or None.

    A click in the gap after a sentence (the space or blank line) counts as
    that sentence, so clicking anywhere on a line does something sensible.
    """
    if not spans:
        return None
    starts = [start for start, _ in spans]
    index = bisect.bisect_right(starts, position) - 1
    return index if index >= 0 else None
