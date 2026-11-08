"""Tests for drag-and-drop PDF detection in the GUI."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QMimeData, QUrl  # noqa: E402

from readaloud.gui import pdf_from_mime  # noqa: E402


def _mime(*urls: QUrl) -> QMimeData:
    mime = QMimeData()
    mime.setUrls(list(urls))
    return mime


def test_first_local_pdf_is_picked(tmp_path: Path) -> None:
    txt, pdf = tmp_path / "notes.txt", tmp_path / "Book.PDF"
    mime = _mime(QUrl.fromLocalFile(str(txt)), QUrl.fromLocalFile(str(pdf)))
    assert pdf_from_mime(mime) == pdf


def test_non_pdf_and_remote_urls_are_ignored(tmp_path: Path) -> None:
    mime = _mime(QUrl.fromLocalFile(str(tmp_path / "a.txt")), QUrl("https://example.com/b.pdf"))
    assert pdf_from_mime(mime) is None
