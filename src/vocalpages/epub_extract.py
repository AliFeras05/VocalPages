"""EPUB loading: chapters in spine order, cleaned to plain readable text.

Each spine document with readable text becomes one ``Section`` (unit
"Chapter"). Navigation documents, scripts, styles, images and page-break
markers are removed; documents left with no text (covers, image-only pages)
are skipped. DRM-protected books are detected up front and rejected.
"""

from __future__ import annotations

import warnings
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from bs4 import BeautifulSoup, Tag

from vocalpages.document import Document, DocumentError, Section

# Encryption algorithms used only to obfuscate embedded fonts; these books are not DRM-protected.
FONT_OBFUSCATION_ALGORITHMS = frozenset(
    {"http://www.idpf.org/2008/embedding", "http://ns.adobe.com/pdf/enc#RC"}
)
_ENC_NS = "{http://www.w3.org/2001/04/xmlenc#}"

REMOVED_TAGS = ("script", "style", "head", "nav", "svg", "img", "picture", "audio", "video", "math", "noscript")
BLOCK_TAGS = (
    "p", "div", "section", "article", "aside", "header", "footer", "blockquote", "pre",
    "h1", "h2", "h3", "h4", "h5", "h6", "li", "dt", "dd", "tr", "figcaption", "hr", "table",
)
SKIPPED_EPUB_TYPES = frozenset({"toc", "landmarks", "page-list", "pagebreak", "lot", "loi"})
SKIPPED_ROLES = frozenset({"doc-toc", "doc-pagebreak", "doc-pagelist", "navigation"})


class EpubError(DocumentError):
    """Raised when an EPUB cannot be opened or read."""


class DrmProtectedError(EpubError):
    """Raised for EPUBs whose content is encrypted with DRM."""


def is_drm_protected(path: str | Path) -> bool:
    """Return True if the EPUB's content (not just its fonts) is encrypted."""
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            if "META-INF/rights.xml" in names:  # Adobe ADEPT and similar schemes
                return True
            if "META-INF/encryption.xml" not in names:
                return False
            root = ElementTree.fromstring(archive.read("META-INF/encryption.xml"))
    except (zipfile.BadZipFile, ElementTree.ParseError, OSError):
        return False  # let the real parser report the problem
    for method in root.iter(f"{_ENC_NS}EncryptionMethod"):
        if method.get("Algorithm") not in FONT_OBFUSCATION_ALGORITHMS:
            return True
    return False


def _is_skipped(tag: Tag) -> bool:
    epub_types = set((tag.get("epub:type") or "").split())
    role = tag.get("role") or ""
    return bool(epub_types & SKIPPED_EPUB_TYPES) or role in SKIPPED_ROLES or tag.has_attr("hidden")


def html_to_text(html: bytes | str) -> tuple[str, str]:
    """Convert one XHTML document to (heading, text).

    Text is plain, with a blank line between blocks. ``heading`` is the first
    h1-h3 in the document, or "" if there is none.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(REMOVED_TAGS):
        tag.decompose()
    for tag in soup.find_all(_is_skipped):
        tag.decompose()

    heading_tag = soup.find(["h1", "h2", "h3"])
    heading = " ".join(heading_tag.get_text(" ").split()) if heading_tag else ""

    for br in soup.find_all("br"):
        br.replace_with("\n")
    for tag in soup.find_all(BLOCK_TAGS):
        tag.insert_before("\n\n")
        tag.insert_after("\n\n")

    root = soup.body or soup
    text = root.get_text().replace("­", "")  # drop soft hyphens
    lines = (" ".join(line.split()) for line in text.split("\n\n"))
    return heading, "\n\n".join(line for line in lines if line)


def _metadata(book: object, field: str) -> str:
    values = book.get_metadata("DC", field)  # type: ignore[attr-defined]
    return str(values[0][0]).strip() if values and values[0] and values[0][0] else ""


def load_epub(path: str | Path) -> Document:
    """Load an EPUB as a ``Document`` with one section per readable chapter.

    Raises:
        DrmProtectedError: if the book is DRM-protected.
        EpubError: if the file is missing, corrupt or has no readable text.
    """
    if not Path(path).is_file():
        raise EpubError("Could not open EPUB: file not found.")
    if is_drm_protected(path):
        raise DrmProtectedError("This EPUB is protected by DRM, which VocalPages cannot read.")

    import ebooklib
    from ebooklib import epub

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # ebooklib emits future/user warnings on every read
            book = epub.read_epub(str(path), options={"ignore_ncx": True})
    except Exception as exc:  # ebooklib raises many unrelated exception types
        raise EpubError(f"Could not open EPUB: {exc}") from exc

    sections: list[Section] = []
    for idref, _linear in book.spine:
        item = book.get_item_with_id(idref)
        if item is None or item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        if isinstance(item, epub.EpubNav) or "nav" in (getattr(item, "properties", None) or []):
            continue
        heading, text = html_to_text(item.get_content())
        if not text:
            continue  # cover, image-only or empty document
        number = len(sections) + 1
        sections.append(Section.from_text(number=number, title=heading or f"Chapter {number}", text=text))

    if not sections:
        raise EpubError("This EPUB has no readable text.")
    return Document(
        title=_metadata(book, "title") or Path(path).stem,
        author=_metadata(book, "creator"),
        format="epub",
        unit="Chapter",
        sections=tuple(sections),
    )
