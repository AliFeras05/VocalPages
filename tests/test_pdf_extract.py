"""Tests for PDF text extraction and cleaning."""

from __future__ import annotations

from pathlib import Path

import pytest

from readaloud.pdf_extract import (
    PdfError,
    TextBlock,
    clean_pages,
    extract_pages,
    is_page_number,
    join_block_lines,
)


def _page(*blocks: tuple[str, float]) -> list[TextBlock]:
    """Build a page from (text, top) pairs; each block is 3% of the page tall."""
    return [TextBlock(text=t, top=top, bottom=top + 0.03) for t, top in blocks]


@pytest.mark.parametrize(
    "text", ["12", " 7 ", "Page 3", "page 3 of 10", "3/10", "- 4 -", "iv", "— 15 —"]
)
def test_is_page_number_accepts_numbers(text: str) -> None:
    assert is_page_number(text)


@pytest.mark.parametrize("text", ["Chapter 1", "12 Angry Men", "In 1999 we left.", ""])
def test_is_page_number_rejects_text(text: str) -> None:
    assert not is_page_number(text)


def test_join_block_lines_repairs_hyphenation_and_newlines() -> None:
    assert join_block_lines("a long exam-\nination of\nthe  case") == "a long examination of the case"


def test_join_block_lines_keeps_real_hyphens() -> None:
    assert join_block_lines("a well-\nKnown name") == "a well-Known name"


def test_clean_pages_removes_repeated_header_and_numbered_footer() -> None:
    pages = [
        _page(("My Book", 0.03), (f"Body of page {n}.", 0.3), (f"Page {n}", 0.95))
        for n in range(1, 5)
    ]
    assert clean_pages(pages) == [f"Body of page {n}." for n in range(1, 5)]


def test_clean_pages_removes_footer_with_changing_numbers() -> None:
    bodies = ["Alpha text.", "Beta text.", "Gamma text.", "Delta text."]
    pages = [
        _page((body, 0.3), (f"Chapter 2 | {n}", 0.95)) for n, body in enumerate(bodies, 10)
    ]
    assert clean_pages(pages) == bodies


def test_clean_pages_keeps_unique_margin_text() -> None:
    pages = [
        _page(("Unique opening line", 0.03), ("Body one.", 0.3)),
        _page(("Body two.", 0.3),),
    ]
    assert clean_pages(pages) == ["Unique opening line\n\nBody one.", "Body two."]


def test_clean_pages_keeps_numbers_in_body() -> None:
    pages = [_page(("Intro", 0.3), ("42", 0.5), ("Outro", 0.7))]
    assert clean_pages(pages) == ["Intro\n\n42\n\nOutro"]


def test_clean_pages_empty_page_gives_empty_string() -> None:
    assert clean_pages([_page(("Text.", 0.3)), []]) == ["Text.", ""]


def test_extract_pages_from_generated_pdf(sample_pdf: Path) -> None:
    pages = extract_pages(sample_pdf)

    assert [p.number for p in pages] == [1, 2, 3, 4, 5]
    assert pages[0].text.startswith("The quick brown fox")
    assert "examination of the evidence" in pages[1].text
    for page in pages:
        assert "Sample Book Title" not in page.text
        assert "Page " not in page.text


def test_extract_pages_flags_page_without_text(sample_pdf: Path) -> None:
    pages = extract_pages(sample_pdf)
    assert [p.has_text for p in pages] == [True, True, True, False, True]


def test_extract_pages_rejects_non_pdf(tmp_path: Path) -> None:
    bogus = tmp_path / "not_a.pdf"
    bogus.write_text("hello")
    with pytest.raises(PdfError):
        extract_pages(bogus)


def test_extract_pages_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(PdfError):
        extract_pages(tmp_path / "missing.pdf")
