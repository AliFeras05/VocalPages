"""Tests for the shared Document model and the PDF loader that produces it."""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from vocalpages.document import Document, Section, UnsupportedFormatError, load_document
from vocalpages.pdf_extract import PdfError


def test_section_from_text_normalises_and_splits() -> None:
    section = Section.from_text(3, "Page 3", "First  line\nwraps here. Second one.\n\n\nNew para.")
    assert section.text == "First line wraps here. Second one.\n\nNew para."
    assert section.sentences == ("First line wraps here.", "Second one.", "New para.")
    assert section.has_text


def test_empty_section_has_no_text() -> None:
    assert not Section.from_text(1, "Page 1", "  \n ").has_text


def test_document_section_lookup_is_one_based() -> None:
    doc = Document("T", "A", "pdf", "Page", (Section.from_text(1, "Page 1", "Hi."),))
    assert doc.section(1).text == "Hi."
    with pytest.raises(IndexError):
        doc.section(2)


def test_load_pdf_builds_page_sections(sample_pdf: Path) -> None:
    doc = load_document(sample_pdf)
    assert doc.format == "pdf"
    assert doc.unit == "Page"
    assert doc.section_count == 5
    assert [s.title for s in doc.sections] == [f"Page {n}" for n in range(1, 6)]
    assert [s.has_text for s in doc.sections] == [True, True, True, False, True]
    assert doc.section(1).sentences[0] == "The quick brown fox jumps over the lazy dog."


def test_pdf_title_falls_back_to_filename(sample_pdf: Path) -> None:
    doc = load_document(sample_pdf)
    assert doc.title == "sample"
    assert doc.author == ""


def test_pdf_title_and_author_from_metadata(tmp_path: Path) -> None:
    path = tmp_path / "meta.pdf"
    pdf = pymupdf.open()
    pdf.new_page().insert_text((72, 300), "Body text.")
    pdf.set_metadata({"title": "A Real Title", "author": "Jane Writer"})
    pdf.save(path)
    pdf.close()
    doc = load_document(path)
    assert (doc.title, doc.author) == ("A Real Title", "Jane Writer")


def test_unsupported_extension(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("hello")
    with pytest.raises(UnsupportedFormatError):
        load_document(path)


def test_bad_pdf_raises_document_error(tmp_path: Path) -> None:
    path = tmp_path / "broken.pdf"
    path.write_text("not a pdf")
    with pytest.raises(PdfError):
        load_document(path)
