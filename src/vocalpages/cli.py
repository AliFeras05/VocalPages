"""Command-line entry point: synthesize one page or chapter to a WAV file."""

from __future__ import annotations

import argparse
import sys
import wave
from pathlib import Path

import numpy as np

from vocalpages.document import DocumentError, load_document
from vocalpages.tts import SAMPLE_RATE, KokoroEngine, TtsError, to_pcm16


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser for ``vocalpages-cli``."""
    parser = argparse.ArgumentParser(
        prog="vocalpages-cli", description="Read one page (PDF) or chapter (EPUB) aloud into a WAV file."
    )
    parser.add_argument("file", type=Path, help="document to read")
    parser.add_argument(
        "--section", "--page", "--chapter", dest="section", type=int, default=1,
        help="1-based page or chapter number (default: 1)",
    )
    parser.add_argument("--out", type=Path, default=Path("section.wav"), help="output WAV file")
    parser.add_argument("--speed", type=float, default=1.0, help="speaking speed, 0.5 to 2.0")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""
    args = build_parser().parse_args(argv)
    try:
        document = load_document(args.file)
    except DocumentError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    unit = document.unit.lower()
    if not 1 <= args.section <= document.section_count:
        print(f"error: {unit} must be between 1 and {document.section_count}", file=sys.stderr)
        return 2
    section = document.section(args.section)
    if not section.has_text:
        print(f"{document.unit} {section.number} has no readable text (it may be a scanned image).")
        return 1

    engine = KokoroEngine()
    print(f"Synthesizing {unit} {section.number} ({len(section.sentences)} sentences)...")
    try:
        audio = np.concatenate([engine.synthesize(s, args.speed) for s in section.sentences])
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
