"""Tests for the regex sentence splitter and sentence positions."""

from __future__ import annotations

import pytest

from readaloud.sentences import (
    locate_sentences,
    normalize_text,
    sentence_at,
    split_sentences,
)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("One here. Two there! Three?", ["One here.", "Two there!", "Three?"]),
        ('He said "Hi." Then left.', ['He said "Hi."', "Then left."]),
        ("Really?! Yes.", ["Really?!", "Yes."]),
        ("(See below.) Next one.", ["(See below.)", "Next one."]),
        ("“Go!” He ran.", ["“Go!”", "He ran."]),
    ],
)
def test_basic_boundaries(text: str, expected: list[str]) -> None:
    assert split_sentences(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Mr. Smith met Dr. Jones. They talked.", ["Mr. Smith met Dr. Jones.", "They talked."]),
        ("Mrs. Brown and Prof. Lee left. Done.", ["Mrs. Brown and Prof. Lee left.", "Done."]),
        ("Use fruit, e.g. Apples or pears. Fine.", ["Use fruit, e.g. Apples or pears.", "Fine."]),
        ("Some, i.e. Most of them. Yes.", ["Some, i.e. Most of them.", "Yes."]),
        ("e.g. this works. Next.", ["e.g. this works.", "Next."]),
        ("See Fig. 3 and No. 5 here. Ok.", ["See Fig. 3 and No. 5 here.", "Ok."]),
        ("J. R. R. Tolkien wrote it. Yes.", ["J. R. R. Tolkien wrote it.", "Yes."]),
        ("She moved to the U.S. Army base. Ok.", ["She moved to the U.S. Army base.", "Ok."]),
    ],
)
def test_abbreviations_do_not_split(text: str, expected: list[str]) -> None:
    assert split_sentences(text) == expected


def test_sentence_final_abbreviation_splits_before_capital() -> None:
    assert split_sentences("Pens, paper, etc. Then we left.") == ["Pens, paper, etc.", "Then we left."]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Pi is 3.14 roughly. Next.", ["Pi is 3.14 roughly.", "Next."]),
        ("It cost $2.50 today. Fine.", ["It cost $2.50 today.", "Fine."]),
        ("Version 1.2.3 shipped. Great.", ["Version 1.2.3 shipped.", "Great."]),
        ("Growth was 0.5. Then 1.5.", ["Growth was 0.5.", "Then 1.5."]),
    ],
)
def test_decimals(text: str, expected: list[str]) -> None:
    assert split_sentences(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Wait... what happened? Nothing.", ["Wait... what happened?", "Nothing."]),
        ("He paused... Then he spoke.", ["He paused...", "Then he spoke."]),
        ("And so… it ends. Yes.", ["And so… it ends.", "Yes."]),
        ("Hmm… Maybe.", ["Hmm…", "Maybe."]),
    ],
)
def test_ellipses(text: str, expected: list[str]) -> None:
    assert split_sentences(text) == expected


def test_lowercase_after_punctuation_does_not_split() -> None:
    assert split_sentences('"Stop!" she cried. Ok.') == ['"Stop!" she cried.', "Ok."]


def test_paragraph_break_ends_sentence() -> None:
    assert split_sentences("No stop here\n\nNew paragraph.") == ["No stop here", "New paragraph."]


def test_long_sentence_is_split_under_limit() -> None:
    text = ", ".join(["word " * 10] * 10) + "."
    sentences = split_sentences(text, max_chars=100)
    assert len(sentences) > 1
    assert all(len(s) <= 100 for s in sentences)
    assert " ".join(sentences).split() == text.split()


def test_empty_text_gives_no_sentences() -> None:
    assert split_sentences("  \n\n ") == []


def test_sentences_can_be_located_in_normalized_text() -> None:
    text = "First  line of\na paragraph. Second one!\n\n  Next   paragraph here."
    display = normalize_text(text)
    sentences = split_sentences(text)
    spans = locate_sentences(display, sentences)
    assert display == "First line of a paragraph. Second one!\n\nNext paragraph here."
    assert [display[a:b] for a, b in spans] == sentences


def test_sentence_at_maps_click_positions() -> None:
    spans = [(0, 10), (11, 20), (22, 30)]
    assert sentence_at(spans, 0) == 0
    assert sentence_at(spans, 9) == 0
    assert sentence_at(spans, 10) == 0  # the space after a sentence
    assert sentence_at(spans, 11) == 1
    assert sentence_at(spans, 21) == 1  # blank line before the next paragraph
    assert sentence_at(spans, 29) == 2
    assert sentence_at(spans, 99) == 2
    assert sentence_at([], 3) is None
