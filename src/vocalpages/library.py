"""The book library: copies of added books plus reading positions, in app data.

Everything lives in the platform user-data directory (never the repo):

- ``library.sqlite3``: one row per book (metadata, progress, position);
- ``books/<sha256>.<ext>``: a private copy of each added file, so the library
  keeps working if the original is moved or deleted.

Books are identified by the SHA-256 of their contents, so adding the same file
twice (even renamed or from another folder) finds the existing entry. No file
paths are stored, only the original file name for display.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_dir

from vocalpages.document import Document, load_document

log = logging.getLogger(__name__)

APP_DIR_NAME = "vocalpages"
# Data folders used by earlier releases (the app was called "Readaloud").
LEGACY_APP_DIR_NAMES = ("readaloud",)
DB_NAME = "library.sqlite3"
BOOKS_DIR_NAME = "books"
LEGACY_RESUME_FILE = "resume_positions.json"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
    id            TEXT PRIMARY KEY,      -- SHA-256 of the file contents
    title         TEXT NOT NULL,
    author        TEXT NOT NULL DEFAULT '',
    format        TEXT NOT NULL,         -- 'pdf' or 'epub'
    unit          TEXT NOT NULL,         -- 'Page' or 'Chapter'
    section_count INTEGER NOT NULL,
    file_name     TEXT NOT NULL,         -- name of the private copy in books/
    original_name TEXT NOT NULL,         -- original file name only, no path
    section       INTEGER NOT NULL DEFAULT 1,
    sentence      INTEGER NOT NULL DEFAULT 0,
    added_at      REAL NOT NULL,
    last_opened   REAL NOT NULL
);
-- Page positions migrated from the pre-library resume file, applied when a
-- book with the same content hash is added.
CREATE TABLE IF NOT EXISTS legacy_positions (
    id      TEXT PRIMARY KEY,
    section INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def default_data_dir() -> Path:
    """Return the platform-standard app data directory."""
    return Path(user_data_dir(APP_DIR_NAME, appauthor=False))


def legacy_data_dirs() -> list[Path]:
    """Return the data folders earlier releases used, newest name first."""
    return [Path(user_data_dir(name, appauthor=False)) for name in LEGACY_APP_DIR_NAMES]


def _has_app_data(folder: Path) -> bool:
    return (folder / DB_NAME).is_file() or (folder / LEGACY_RESUME_FILE).is_file()


def migrate_legacy_data_dir(new_dir: Path, legacy_dirs: list[Path]) -> Path | None:
    """Copy an earlier release's data folder into ``new_dir`` if needed.

    Runs only when ``new_dir`` has no library yet and a legacy folder has one.
    The legacy folder is copied, never moved or deleted, so an older version of
    the app keeps working. Returns the folder that was copied, or None.
    """
    if _has_app_data(new_dir):
        return None
    for legacy in legacy_dirs:
        if legacy.resolve() != new_dir.resolve() and _has_app_data(legacy):
            shutil.copytree(legacy, new_dir, dirs_exist_ok=True)
            log.info("Copied library data from the previous app folder")
            return legacy
    return None


def fingerprint(path: str | Path) -> str:
    """Return the SHA-256 hex digest of a file's contents."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class BookRecord:
    """One library entry."""

    id: str
    title: str
    author: str
    format: str
    unit: str
    section_count: int
    file_name: str
    original_name: str
    section: int
    sentence: int

    @property
    def progress_text(self) -> str:
        """Short progress label such as "Page 40 of 210" or "Ch 3 of 12"."""
        label = "Ch" if self.unit == "Chapter" else self.unit
        return f"{label} {self.section} of {self.section_count}"


class Library:
    """SQLite-backed library. Use from one thread (the GUI thread)."""

    def __init__(self, data_dir: Path | None = None, legacy_dirs: list[Path] | None = None) -> None:
        """Open (or create) the library in ``data_dir``.

        With the default ``data_dir``, data from an earlier release's folder is
        copied over first; pass ``legacy_dirs`` to control that explicitly.
        """
        self.data_dir = data_dir or default_data_dir()
        if legacy_dirs is None:
            legacy_dirs = legacy_data_dirs() if data_dir is None else []
        migrate_legacy_data_dir(self.data_dir, legacy_dirs)
        self.books_dir = self.data_dir / BOOKS_DIR_NAME
        self.books_dir.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.data_dir / DB_NAME)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_SCHEMA)
        self._migrate_legacy_resume_file()

    def close(self) -> None:
        """Close the database connection."""
        self._db.close()

    # ----- queries --------------------------------------------------------

    def books(self) -> list[BookRecord]:
        """All books, most recently opened first."""
        rows = self._db.execute("SELECT * FROM books ORDER BY last_opened DESC").fetchall()
        return [self._record(row) for row in rows]

    def get(self, book_id: str) -> BookRecord | None:
        """Return the book with ``book_id``, or None."""
        row = self._db.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
        return self._record(row) if row else None

    def book_path(self, book_id: str) -> Path:
        """Path of the library's private copy of a book."""
        record = self.get(book_id)
        if record is None:
            raise KeyError(book_id)
        return self.books_dir / record.file_name

    def load(self, book_id: str) -> Document:
        """Load the library copy of a book and mark it as just opened.

        Raises:
            KeyError: if the book is not in the library.
            DocumentError: if the stored copy cannot be read.
        """
        document = load_document(self.book_path(book_id))
        self._touch(book_id)
        return document

    # ----- changes --------------------------------------------------------

    def add(self, path: str | Path) -> tuple[BookRecord, Document, bool]:
        """Add a book (or find it if already present) and load it.

        Returns ``(record, document, is_new)``. The original file is only read;
        a copy is stored in the library folder.

        Raises:
            UnsupportedFormatError / DocumentError: if the file cannot be read.
        """
        path = Path(path)
        book_id = fingerprint(path)
        existing = self.get(book_id)
        if existing is not None:
            return existing, self.load(book_id), False

        document = load_document(path)  # validate before storing anything
        file_name = f"{book_id}{path.suffix.lower()}"
        shutil.copy2(path, self.books_dir / file_name)

        legacy = self._db.execute(
            "SELECT section FROM legacy_positions WHERE id = ?", (book_id,)
        ).fetchone()
        section = legacy["section"] if legacy and legacy["section"] <= document.section_count else 1
        now = time.time()
        with self._db:
            self._db.execute(
                "INSERT INTO books (id, title, author, format, unit, section_count, file_name,"
                " original_name, section, sentence, added_at, last_opened)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
                (
                    book_id, document.title, document.author, document.format, document.unit,
                    document.section_count, file_name, path.name, section, now, now,
                ),
            )
            self._db.execute("DELETE FROM legacy_positions WHERE id = ?", (book_id,))
        record = self.get(book_id)
        assert record is not None
        return record, document, True

    def save_position(self, book_id: str, section: int, sentence: int) -> None:
        """Remember the reading position (1-based section, 0-based sentence)."""
        with self._db:
            self._db.execute(
                "UPDATE books SET section = ?, sentence = ? WHERE id = ?",
                (section, sentence, book_id),
            )

    def remove(self, book_id: str) -> None:
        """Remove a book and the library's private copy. The user's original file is untouched."""
        record = self.get(book_id)
        if record is None:
            return
        with self._db:
            self._db.execute("DELETE FROM books WHERE id = ?", (book_id,))
        (self.books_dir / record.file_name).unlink(missing_ok=True)

    # ----- internals ------------------------------------------------------

    def _touch(self, book_id: str) -> None:
        with self._db:
            self._db.execute("UPDATE books SET last_opened = ? WHERE id = ?", (time.time(), book_id))

    @staticmethod
    def _record(row: sqlite3.Row) -> BookRecord:
        return BookRecord(
            id=row["id"], title=row["title"], author=row["author"], format=row["format"],
            unit=row["unit"], section_count=row["section_count"], file_name=row["file_name"],
            original_name=row["original_name"], section=row["section"], sentence=row["sentence"],
        )

    def _migrate_legacy_resume_file(self) -> None:
        """Import page positions from the old ``resume_positions.json`` once.

        The old file is left in place (read-only use), so downgrading still works.
        """
        done = self._db.execute("SELECT value FROM meta WHERE key = 'legacy_resume_migrated'").fetchone()
        legacy_file = self.data_dir / LEGACY_RESUME_FILE
        if done or not legacy_file.is_file():
            return
        try:
            data = json.loads(legacy_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.warning("Old resume file is unreadable; skipping migration")
            data = {}
        entries = [
            (key, page) for key, page in (data.items() if isinstance(data, dict) else [])
            if isinstance(key, str) and isinstance(page, int) and page > 0
        ]
        with self._db:
            self._db.executemany(
                "INSERT OR IGNORE INTO legacy_positions (id, section) VALUES (?, ?)", entries
            )
            self._db.execute(
                "INSERT INTO meta (key, value) VALUES ('legacy_resume_migrated', '1')"
            )
        log.info("Migrated %d saved reading position(s)", len(entries))
