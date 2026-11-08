"""Tests for the library: de-duplication, private copies, positions and migration."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from vocalpages.document import UnsupportedFormatError
from vocalpages.library import Library, fingerprint, migrate_legacy_data_dir


@pytest.fixture
def library(tmp_path: Path) -> Library:
    lib = Library(tmp_path / "appdata")
    yield lib
    lib.close()


def test_add_copies_book_and_reads_metadata(library: Library, sample_pdf: Path) -> None:
    record, document, is_new = library.add(sample_pdf)
    assert is_new
    assert record.id == fingerprint(sample_pdf)
    assert (record.title, record.format, record.unit) == ("sample", "pdf", "Page")
    assert record.section_count == document.section_count == 5
    assert record.original_name == "sample.pdf"
    copy = library.book_path(record.id)
    assert copy.parent == library.books_dir
    assert copy.read_bytes() == sample_pdf.read_bytes()


def test_adding_same_content_twice_does_not_duplicate(library: Library, sample_pdf: Path, tmp_path: Path) -> None:
    renamed = tmp_path / "elsewhere" / "renamed copy.pdf"
    renamed.parent.mkdir()
    shutil.copy(sample_pdf, renamed)

    first, _, first_new = library.add(sample_pdf)
    second, _, second_new = library.add(renamed)

    assert first_new and not second_new
    assert first.id == second.id
    assert len(library.books()) == 1


def test_library_works_after_original_is_deleted(library: Library, sample_pdf: Path) -> None:
    record, _, _ = library.add(sample_pdf)
    sample_pdf.unlink()
    assert library.load(record.id).section_count == 5


def test_remove_keeps_the_original_file(library: Library, sample_pdf: Path) -> None:
    record, _, _ = library.add(sample_pdf)
    copy = library.book_path(record.id)
    library.remove(record.id)
    assert library.get(record.id) is None
    assert not copy.exists()
    assert sample_pdf.exists()


def test_sentence_level_position_is_saved_and_restored(tmp_path: Path, sample_pdf: Path) -> None:
    data_dir = tmp_path / "appdata"
    lib = Library(data_dir)
    record, _, _ = lib.add(sample_pdf)
    lib.save_position(record.id, section=3, sentence=1)
    lib.close()

    reopened = Library(data_dir)  # simulates closing and reopening the app
    saved = reopened.get(record.id)
    assert saved is not None
    assert (saved.section, saved.sentence) == (3, 1)
    assert saved.progress_text == "Page 3 of 5"
    reopened.close()


def test_re_adding_a_known_book_keeps_its_position(library: Library, sample_pdf: Path) -> None:
    record, _, _ = library.add(sample_pdf)
    library.save_position(record.id, 2, 1)
    again, _, is_new = library.add(sample_pdf)
    assert not is_new
    assert (again.section, again.sentence) == (2, 1)


def test_unsupported_file_is_rejected_and_not_stored(library: Library, tmp_path: Path) -> None:
    notes = tmp_path / "notes.txt"
    notes.write_text("hello")
    with pytest.raises(UnsupportedFormatError):
        library.add(notes)
    assert library.books() == []
    assert list(library.books_dir.iterdir()) == []


def test_books_are_listed_most_recent_first(library: Library, sample_pdf: Path, tmp_path: Path) -> None:
    other = tmp_path / "other.pdf"
    other.write_bytes(sample_pdf.read_bytes() + b"\n% different bytes\n")
    first, _, _ = library.add(sample_pdf)
    second, _, _ = library.add(other)
    assert [b.id for b in library.books()] == [second.id, first.id]
    library.load(first.id)
    assert [b.id for b in library.books()][0] == first.id


def test_chapter_progress_text() -> None:
    from vocalpages.library import BookRecord

    record = BookRecord("x", "T", "", "epub", "Chapter", 12, "x.epub", "t.epub", 3, 0)
    assert record.progress_text == "Ch 3 of 12"


def test_legacy_resume_positions_are_migrated(tmp_path: Path, sample_pdf: Path) -> None:
    data_dir = tmp_path / "appdata"
    data_dir.mkdir()
    legacy = data_dir / "resume_positions.json"
    legacy.write_text(json.dumps({fingerprint(sample_pdf): 4, "bogus": "x"}))

    lib = Library(data_dir)
    record, _, _ = lib.add(sample_pdf)
    assert (record.section, record.sentence) == (4, 0)
    assert legacy.exists()  # the old file is left untouched
    lib.close()


def test_legacy_migration_runs_only_once(tmp_path: Path, sample_pdf: Path) -> None:
    data_dir = tmp_path / "appdata"
    data_dir.mkdir()
    (data_dir / "resume_positions.json").write_text(json.dumps({fingerprint(sample_pdf): 4}))
    Library(data_dir).close()

    lib = Library(data_dir)  # second start: legacy row still pending, not re-imported
    record, _, _ = lib.add(sample_pdf)
    lib.save_position(record.id, 1, 0)
    lib.remove(record.id)
    record, _, _ = lib.add(sample_pdf)
    assert record.section == 1  # legacy position was consumed by the first add
    lib.close()


def test_old_data_folder_is_copied_on_first_launch(tmp_path: Path, sample_pdf: Path) -> None:
    old_dir = tmp_path / "readaloud"
    old = Library(old_dir, legacy_dirs=[])
    record, _, _ = old.add(sample_pdf)
    old.save_position(record.id, 3, 1)
    old.close()
    (old_dir / "resume_positions.json").write_text("{}")

    new_dir = tmp_path / "vocalpages"
    lib = Library(new_dir, legacy_dirs=[old_dir])
    migrated = lib.get(record.id)
    assert migrated is not None
    assert (migrated.section, migrated.sentence) == (3, 1)
    assert lib.load(record.id).section_count == 5  # book copy came along
    lib.close()

    # The old folder is left exactly where it was.
    assert (old_dir / "library.sqlite3").is_file()
    assert (old_dir / "books" / f"{record.id}.pdf").is_file()


def test_migration_does_not_overwrite_an_existing_new_library(tmp_path: Path, sample_pdf: Path) -> None:
    old_dir, new_dir = tmp_path / "readaloud", tmp_path / "vocalpages"
    old = Library(old_dir, legacy_dirs=[])
    old.add(sample_pdf)
    old.close()
    Library(new_dir, legacy_dirs=[]).close()  # new library already exists (empty)

    assert migrate_legacy_data_dir(new_dir, [old_dir]) is None
    lib = Library(new_dir, legacy_dirs=[old_dir])
    assert lib.books() == []
    lib.close()


def test_no_legacy_folder_means_fresh_library(tmp_path: Path) -> None:
    lib = Library(tmp_path / "vocalpages", legacy_dirs=[tmp_path / "missing"])
    assert lib.books() == []
    lib.close()
