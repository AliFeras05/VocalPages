"""Command-line entry point: synthesize a single PDF page to a WAV file."""

from __future__ import annotations

import argparse
import sys
import wave
from pathlib import Path

import numpy as np

from readaloud.pdf_extract import PdfError, extract_pages
from readaloud.tts import SAMPLE_RATE, KokoroEngine, TtsError, split_into_segments, to_pcm16


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser for ``readaloud-cli``."""
    parser = argparse.ArgumentParser(
        prog="readaloud-cli", description="Read one PDF page aloud into a WAV file."
    )
    parser.add_argument("pdf", type=Path, help="PDF file to read")
    parser.add_argument("--page", type=int, default=1, help="1-based page number (default: 1)")
    parser.add_argument("--out", type=Path, default=Path("page.wav"), help="output WAV file")
    parser.add_argument("--speed", type=float, default=1.0, help="speaking speed, 0.5 to 2.0")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""
    args = build_parser().parse_args(argv)
    try:
        pages = extract_pages(args.pdf)
    except PdfError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if not 1 <= args.page <= len(pages):
        print(f"error: page must be between 1 and {len(pages)}", file=sys.stderr)
        return 2
    page = pages[args.page - 1]
    if not page.has_text:
        print(f"Page {page.number} has no extractable text (it may be a scanned image).")
        return 1

    engine = KokoroEngine()
    segments = split_into_segments(page.text)
    print(f"Synthesizing page {page.number} ({len(segments)} segments)...")
    try:
        audio = np.concatenate([engine.synthesize(s, args.speed) for s in segments])
    except TtsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    with wave.open(str(args.out), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(to_pcm16(audio))
    print(f"Wrote {args.out.name} ({len(audio) / SAMPLE_RATE:.1f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
