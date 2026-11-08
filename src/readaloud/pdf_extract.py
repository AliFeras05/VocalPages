"""PDF text extraction and cleaning.

Text is pulled page by page with PyMuPDF as positioned blocks. Blocks that sit
in the top or bottom margin and repeat across pages (running headers and
footers) are dropped, as are bare page numbers. The remaining blocks are joined
into paragraphs with line-break hyphenation repaired.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import pymupdf

# Fraction of the page height treated as the top/bottom margin.
MARGIN_FRACTION = 0.12
# Short first/last blocks are also header/footer candidates even outside the margin.
SHORT_EDGE_BLOCK_CHARS = 80
# A margin block is a running header/footer if it repeats on this share of pages.
REPEAT_FRACTION = 0.3

_PAGE_NUMBER_RE = re.compile(
    r"^[\s\-–—]*(page\s+)?(\d+|[ivxlcdm]+)(\s*(of|/)\s*\d+)?[\s\-–—]*$",
    re.IGNORECASE,
)
_HYPHEN_BREAK_RE = re.compile(r"(\w)-\n(?=[a-z])")
_HYPHEN_KEEP_RE = re.compile(r"-\n(?=\S)")
_WHITESPACE_RE = re.compile(r"\s+")


class PdfError(Exception):
    """Raised when a PDF cannot be opened or read."""


@dataclass(frozen=True)
class TextBlock:
    """A block of text with its vertical position relative to the page (0 = top, 1 = bottom)."""

    text: str
    top: float
    bottom: float


@dataclass(frozen=True)
class Page:
    """Cleaned text of one PDF page. ``number`` is 1-based."""

    number: int
    text: str

    @property
    def has_text(self) -> bool:
        """True if the page has readable text (False for scanned/image-only pages)."""
        return bool(self.text.strip())


def is_page_number(text: str) -> bool:
    """Return True if ``text`` is only a page number such as ``12``, ``Page 3 of 9`` or ``- iv -``."""
    return bool(_PAGE_NUMBER_RE.match(text.strip()))


def normalize_for_matching(text: str) -> str:
    """Normalise a block so running headers match across pages (case, spacing, digits)."""
    collapsed = _WHITESPACE_RE.sub(" ", text).strip().lower()
    return re.sub(r"\d+", "#", collapsed)


def join_block_lines(text: str) -> str:
    """Join the lines of one block into a single paragraph, repairing hyphenated breaks."""
    dehyphenated = _HYPHEN_BREAK_RE.sub(r"\1", text.strip())
    dehyphenated = _HYPHEN_KEEP_RE.sub("-", dehyphenated)
    return _WHITESPACE_RE.sub(" ", dehyphenated).strip()


def _is_edge_block(block: TextBlock, index: int, count: int) -> bool:
    in_margin = block.bottom <= MARGIN_FRACTION or block.top >= 1 - MARGIN_FRACTION
    short_end = index in (0, count - 1) and len(block.text.strip()) <= SHORT_EDGE_BLOCK_CHARS
    return in_margin or short_end


def clean_pages(pages: Sequence[Sequence[TextBlock]]) -> list[str]:
    """Clean raw blocks of every page and return one text string per page.

    Running headers/footers are detected across the whole document, so all pages
    must be passed together. Empty pages yield an empty string.
    """
    edge_flags = [
        [_is_edge_block(b, i, len(blocks)) for i, b in enumerate(blocks)] for blocks in pages
    ]

    counts: Counter[str] = Counter()
    for blocks, flags in zip(pages, edge_flags):
        keys = {normalize_for_matching(b.text) for b, edge in zip(blocks, flags) if edge}
        counts.update(keys)

    pages_with_text = sum(1 for blocks in pages if any(b.text.strip() for b in blocks))
    threshold = max(2, int(REPEAT_FRACTION * pages_with_text + 0.999))
    repeated = {key for key, n in counts.items() if n >= threshold}

    cleaned: list[str] = []
    for blocks, flags in zip(pages, edge_flags):
        paragraphs = []
        for block, edge in zip(blocks, flags):
            if not block.text.strip():
                continue
            if edge and (is_page_number(block.text) or normalize_for_matching(block.text) in repeated):
                continue
            paragraphs.append(join_block_lines(block.text))
        cleaned.append("\n\n".join(p for p in paragraphs if p))
    return cleaned


def _read_blocks(page: pymupdf.Page) -> list[TextBlock]:
    height = page.rect.height or 1.0
    blocks = []
    for x0, y0, x1, y1, text, _block_no, block_type in page.get_text("blocks", sort=True):
        if block_type == 0:  # 0 = text, 1 = image
            blocks.append(TextBlock(text=text, top=y0 / height, bottom=y1 / height))
    return blocks


def extract_pages(path: str | Path) -> list[Page]:
    """Open the PDF at ``path`` and return the cleaned text of every page.

    Raises:
        PdfError: if the file is missing, not a PDF, or password-protected.
    """
    try:
        doc = pymupdf.open(path)
    except Exception as exc:  # PyMuPDF raises several unrelated exception types
        raise PdfError(f"Could not open PDF: {exc}") from exc

    with doc:
        if doc.needs_pass:
            raise PdfError("This PDF is password-protected.")
        if not doc.is_pdf:
            raise PdfError("This file is not a PDF.")
        raw = [_read_blocks(page) for page in doc]

    return [Page(number=i + 1, text=text) for i, text in enumerate(clean_pages(raw))]
