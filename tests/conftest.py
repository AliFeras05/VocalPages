"""Shared fixtures. Test PDFs are generated on the fly, never committed."""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

BODY_TEXT = [
    "The quick brown fox jumps over the lazy dog. It was a calm and pleasant "
    "morning in the small village by the river.",
    "Second page body. The committee reached an agreement after a long exam-\n"
    "ination of the evidence presented.",
    "Third page body. Rain fell softly on the roofs while the children read "
    "their books by the window.",
    "Fifth page body, after a page that holds only an image.",
]


def make_sample_pdf(path: Path) -> Path:
    """Write a 5-page PDF: running header, numbered footer, and page 4 blank (scan-like)."""
    doc = pymupdf.open()
    bodies = iter(BODY_TEXT)
    for number in range(1, 6):
        page = doc.new_page(width=595, height=842)  # A4 in points
        if number == 4:
            continue  # no text layer at all, like a scanned page
        page.insert_text((72, 40), "A Sample Book Title", fontsize=9)
        page.insert_textbox(pymupdf.Rect(72, 120, 523, 700), next(bodies), fontsize=12)
        page.insert_text((280, 815), f"Page {number}", fontsize=9)
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    """Path to a freshly generated sample PDF."""
    return make_sample_pdf(tmp_path / "sample.pdf")
