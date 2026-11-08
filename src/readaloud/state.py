"""Per-PDF resume positions, stored in the user's app data directory.

PDFs are identified by a SHA-256 fingerprint of their contents, so the saved
state never contains file paths and still works if a file is moved or renamed.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from platformdirs import user_data_dir

log = logging.getLogger(__name__)

STATE_FILE_NAME = "resume_positions.json"


def default_state_path() -> Path:
    """Return the platform-standard location of the resume file."""
    return Path(user_data_dir("readaloud", appauthor=False)) / STATE_FILE_NAME


def fingerprint(pdf_path: str | Path) -> str:
    """Return a SHA-256 hex digest of the file's contents."""
    digest = hashlib.sha256()
    with open(pdf_path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ResumeStore:
    """Small JSON store mapping a PDF fingerprint to the last page reached."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_state_path()
        self._data: dict[str, int] = self._load()

    def _load(self) -> dict[str, int]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            log.warning("Resume file is unreadable; starting fresh")
            return {}
        if not isinstance(raw, dict):
            return {}
        return {k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, int) and v > 0}

    def get(self, key: str) -> int | None:
        """Return the saved 1-based page for ``key``, or None."""
        return self._data.get(key)

    def set(self, key: str, page: int) -> None:
        """Save ``page`` for ``key`` and write the file."""
        if self._data.get(key) == page:
            return
        self._data[key] = page
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            log.warning("Could not save resume position")
