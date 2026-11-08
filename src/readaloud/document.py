"""Format-independent document model.

Every loader (PDF, EPUB) turns a file into a ``Document`` made of numbered
``Section`` objects (PDF pages or EPUB chapters), each already split into
sentences. Playback, export and the library only ever see this structure.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from readaloud.tts import normalize_page_text, split_into_segments


class DocumentError(Exception):
    """Raised when a file cannot be opened as a readable document."""


class UnsupportedFormatError(DocumentError):
    """Raised for file types the app cannot read."""


@dataclass(frozen=True)
class Section:
    """One readable unit: a PDF page or an EPUB chapter. ``number`` is 1-based."""

    number: int
    title: str
    text: str
    sentences: tuple[str, ...]

    @classmethod
    def from_text(cls, number: int, title: str, text: str) -> "Section":
        """Build a section from raw text, normalising whitespace and splitting sentences."""
        display = normalize_page_text(text)
        return cls(number=number, title=title, text=display, sentences=tuple(split_into_segments(display)))

    @property
    def has_text(self) -> bool:
        """True if there is anything to read (False for scanned or image-only sections)."""
        return bool(self.sentences)


@dataclass(frozen=True)
class Document:
    """A loaded book: metadata plus its sections in reading order."""

    title: str
    author: str
    format: str  # "pdf" or "epub"
    unit: str  # what a section is called in the UI: "Page" or "Chapter"
    sections: tuple[Section, ...]

    @property
    def section_count(self) -> int:
        """Number of sections."""
        return len(self.sections)

    def section(self, number: int) -> Section:
        """Return the section with the given 1-based number."""
        if not 1 <= number <= len(self.sections):
            raise IndexError(f"{self.unit} {number} is out of range")
        return self.sections[number - 1]


SUPPORTED_EXTENSIONS = (".pdf",)


def load_document(path: str | Path) -> Document:
    """Open ``path`` with the loader for its file type.

    Raises:
        UnsupportedFormatError: if the extension is not supported.
        DocumentError: if the file cannot be read.
    """
    suffix = Path(path).suffix.lower()
    if suffix == ".pdf":
        from readaloud.pdf_extract import load_pdf

        return load_pdf(path)
    supported = ", ".join(SUPPORTED_EXTENSIONS)
    raise UnsupportedFormatError(f"Unsupported file type '{suffix or 'none'}'. Supported: {supported}.")
