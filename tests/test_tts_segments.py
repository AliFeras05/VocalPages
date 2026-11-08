"""Tests for the pure text helpers in the TTS module (no model needed)."""

from __future__ import annotations

import threading
import time

import numpy as np

from readaloud.tts import (
    FairLock,
    clamp_speed,
    locate_segments,
    normalize_page_text,
    split_into_segments,
    to_pcm16,
)


def test_splits_sentences() -> None:
    assert split_into_segments("One here. Two there! Three?") == ["One here.", "Two there!", "Three?"]


def test_closing_quote_stays_with_sentence() -> None:
    assert split_into_segments('He said "Hi." Then left.') == ['He said "Hi."', "Then left."]


def test_paragraph_break_ends_segment() -> None:
    assert split_into_segments("No stop here\n\nNew paragraph.") == ["No stop here", "New paragraph."]


def test_abbreviation_does_not_split() -> None:
    assert split_into_segments("Dr. Smith arrived. He sat.") == ["Dr. Smith arrived.", "He sat."]


def test_long_sentence_is_split_under_limit() -> None:
    text = ", ".join(["word " * 10] * 10) + "."
    segments = split_into_segments(text, max_chars=100)
    assert len(segments) > 1
    assert all(len(s) <= 100 for s in segments)
    assert " ".join(segments).split() == text.split()


def test_empty_text_gives_no_segments() -> None:
    assert split_into_segments("  \n\n ") == []


def test_clamp_speed() -> None:
    assert clamp_speed(0.1) == 0.5
    assert clamp_speed(1.3) == 1.3
    assert clamp_speed(5) == 2.0


def test_to_pcm16_scales_and_clips() -> None:
    pcm = np.frombuffer(to_pcm16(np.array([0.0, 1.0, -2.0], dtype=np.float32)), dtype="<i2")
    assert pcm.tolist() == [0, 32767, -32767]


def test_segments_can_be_located_in_display_text() -> None:
    text = "First  line of\na paragraph. Second one!\n\n  Next   paragraph here."
    display = normalize_page_text(text)
    segments = split_into_segments(text)
    spans = locate_segments(display, segments)
    assert display == "First line of a paragraph. Second one!\n\nNext paragraph here."
    assert [display[a:b] for a, b in spans] == segments


def test_fair_lock_alternates_between_threads() -> None:
    lock = FairLock()
    order: list[str] = []
    started = threading.Event()

    def greedy() -> None:
        for _ in range(4):
            with lock:
                order.append("export")
                started.set()
                time.sleep(0.02)

    def player() -> None:
        started.wait()
        with lock:
            order.append("play")

    threads = [threading.Thread(target=greedy), threading.Thread(target=player)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert order.index("play") <= 2
