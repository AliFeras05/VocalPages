"""Tests for home-page helpers: drag-and-drop file detection and format checks."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QMimeData, QUrl  # noqa: E402

from vocalpages.home import is_supported, local_file_from_mime  # noqa: E402


def _mime(*urls: QUrl) -> QMimeData:
    mime = QMimeData()
    mime.setUrls(list(urls))
    return mime


def test_first_local_file_is_picked(tmp_path: Path) -> None:
    first, second = tmp_path / "notes.txt", tmp_path / "Book.PDF"
    mime = _mime(QUrl("https://example.com/x.pdf"), QUrl.fromLocalFile(str(first)), QUrl.fromLocalFile(str(second)))
    assert local_file_from_mime(mime) == first


def test_remote_only_drop_is_ignored() -> None:
    assert local_file_from_mime(_mime(QUrl("https://example.com/b.pdf"))) is None


@pytest.mark.parametrize("name,ok", [("a.pdf", True), ("B.PDF", True), ("c.epub", True), ("d.Epub", True),
                                     ("e.txt", False), ("f.mobi", False), ("noext", False)])
def test_is_supported(name: str, ok: bool) -> None:
    assert is_supported(Path(name)) is ok
