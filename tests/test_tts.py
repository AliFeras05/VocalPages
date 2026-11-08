"""Tests for the model-free helpers in the TTS module."""

from __future__ import annotations

import threading
import time

import numpy as np

from vocalpages.tts import FairLock, clamp_speed, to_pcm16


def test_clamp_speed() -> None:
    assert clamp_speed(0.1) == 0.5
    assert clamp_speed(1.3) == 1.3
    assert clamp_speed(5) == 2.0


def test_to_pcm16_scales_and_clips() -> None:
    pcm = np.frombuffer(to_pcm16(np.array([0.0, 1.0, -2.0], dtype=np.float32)), dtype="<i2")
    assert pcm.tolist() == [0, 32767, -32767]


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
