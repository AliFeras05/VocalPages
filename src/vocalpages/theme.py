"""Design tokens and the application stylesheet.

Every color, font size, spacing value and corner radius used by the UI is
defined here. Widgets never hard-code styles: they set an ``objectName`` (or a
dynamic property) and the single stylesheet built by ``build_stylesheet`` does
the rest. Both palettes define exactly the same tokens, so no widget needs to
know which theme is active.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, fields
from pathlib import Path

log = logging.getLogger(__name__)

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"

# ----- palettes ---------------------------------------------------------------


@dataclass(frozen=True)
class Palette:
    """Color tokens (hex strings). Both themes define every field."""

    name: str
    background: str  # main window / reader page
    surface: str  # player bar, drop zone fill
    sidebar: str
    separator: str  # hairlines between areas
    hover: str  # background of hovered buttons and list items
    selected: str  # background of the current book in the sidebar
    text: str
    text_muted: str  # secondary text (taglines, progress labels)
    text_disabled: str
    accent: str  # active state, primary actions, progress
    accent_hover: str
    accent_pressed: str
    on_accent: str  # text/icons drawn on an accent fill
    accent_soft: str  # drop zone fill while a file is dragged over it
    highlight: str  # background of the sentence being read
    highlight_text: str
    error_text: str
    error_background: str
    progress_track: str
    icon: str  # default icon tint
    icon_disabled: str


LIGHT = Palette(
    name="light",
    background="#FBF7F6",
    surface="#F7F0EE",
    sidebar="#F3E9E7",
    separator="#E6D8D5",
    hover="#EADBD8",
    selected="#E9D6D8",
    text="#2B2526",
    text_muted="#685B5D",
    text_disabled="#A99D9E",
    accent="#722F37",
    accent_hover="#5E262D",
    accent_pressed="#4F1F26",
    on_accent="#FFFFFF",
    accent_soft="#F5E8EA",
    highlight="#F3E3E5",
    highlight_text="#2B2526",
    error_text="#8E1B2A",
    error_background="#F8E9EA",
    progress_track="#E3D3D0",
    icon="#4A3F41",
    icon_disabled="#BDB1B2",
)

DARK = Palette(
    name="dark",
    background="#1C1A1A",
    surface="#221F1F",
    sidebar="#262122",
    separator="#352D2E",
    hover="#332B2D",
    selected="#3A2A2D",
    text="#EDE6E5",
    text_muted="#B3A6A5",
    text_disabled="#6B6162",
    accent="#C8707A",  # lighter wine derived from #722F37, readable on dark surfaces
    accent_hover="#D3848D",
    accent_pressed="#DE99A1",
    on_accent="#1C1A1A",
    accent_soft="#2E2224",
    highlight="#722F37",
    highlight_text="#EDE6E5",
    error_text="#F09AA3",
    error_background="#3A2226",
    progress_track="#3D3435",
    icon="#D6CBCA",
    icon_disabled="#5E5556",
)

PALETTES: dict[str, Palette] = {"light": LIGHT, "dark": DARK}


def token_names() -> list[str]:
    """Names of the color tokens every palette defines."""
    return [f.name for f in fields(Palette) if f.name != "name"]


# ----- typography, spacing, shape --------------------------------------------

FONT_UI = "Inter"
FONT_READING = "Literata"

FONT_SIZE_SMALL = 12  # px
FONT_SIZE_BODY = 14
FONT_SIZE_LABEL = 15
FONT_SIZE_LARGE = 20
FONT_SIZE_TITLE = 44
FONT_SIZE_READING = 19
READING_LINE_HEIGHT = 1.6
READING_MAX_CHARS = 70

GRID = 8  # every margin and gap is a multiple of this


def space(units: float) -> int:
    """Spacing on the 8px grid: ``space(2) == 16``."""
    return int(GRID * units)


RADIUS_SMALL = 8
RADIUS_MEDIUM = 10
RADIUS_LARGE = 12

ICON_SMALL = 16
ICON_MEDIUM = 20
ICON_LARGE = 24
BUTTON_SIZE = 40  # square icon buttons
PLAY_BUTTON_SIZE = 56
SIDEBAR_WIDTH = 272
PROGRESS_BAR_HEIGHT = 3
BOTTOM_BAR_HEIGHT = 80  # player bar and sidebar footer share one baseline


# ----- contrast (WCAG 2.x) ----------------------------------------------------


def relative_luminance(hex_color: str) -> float:
    """WCAG relative luminance of a ``#RRGGBB`` color."""
    value = hex_color.lstrip("#")
    channels = [int(value[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(foreground: str, background: str) -> float:
    """WCAG contrast ratio between two colors (1.0 to 21.0)."""
    high, low = sorted((relative_luminance(foreground), relative_luminance(background)), reverse=True)
    return (high + 0.05) / (low + 0.05)


# Text pairs need 4.5:1 (WCAG AA); icon and UI-component pairs need 3:1.
TEXT_PAIRS = [
    ("text", "background"), ("text", "sidebar"), ("text", "surface"), ("text", "hover"),
    ("text", "selected"), ("text_muted", "background"), ("text_muted", "sidebar"),
    ("text_muted", "surface"), ("text_muted", "hover"), ("text_muted", "selected"),
    ("accent", "background"), ("accent", "sidebar"), ("accent", "surface"),
    ("on_accent", "accent"), ("on_accent", "accent_hover"), ("on_accent", "accent_pressed"),
    ("highlight_text", "highlight"), ("error_text", "error_background"), ("error_text", "background"),
]
NON_TEXT_PAIRS = [
    ("icon", "background"), ("icon", "sidebar"), ("icon", "surface"), ("icon", "hover"),
    ("icon", "selected"), ("accent", "hover"), ("accent", "selected"), ("accent", "progress_track"),
    ("accent", "accent_soft"),
]


# ----- fonts -------------------------------------------------------------------


def load_fonts() -> list[str]:
    """Register the bundled Inter and Literata fonts with Qt; return the families loaded."""
    from PySide6.QtGui import QFontDatabase

    families: set[str] = set()
    for path in sorted(FONTS_DIR.glob("*/*.ttf")):
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id < 0:
            log.warning("Could not load bundled font %s", path.name)
            continue
        families.update(QFontDatabase.applicationFontFamilies(font_id))
    return sorted(families)


# ----- stylesheet --------------------------------------------------------------


def build_stylesheet(p: Palette) -> str:
    """Return the application-wide Qt stylesheet for palette ``p``."""
    return f"""
* {{
    font-family: "{FONT_UI}";
    font-size: {FONT_SIZE_BODY}px;
    color: {p.text};
}}
QMainWindow, QWidget#centralArea, QStackedWidget, QWidget#homePage, QWidget#readerPage {{
    background: {p.background};
}}
QToolTip {{
    background: {p.text};
    color: {p.background};
    border: none;
    border-radius: {RADIUS_SMALL - 2}px;
    padding: {space(0.5)}px {space(1)}px;
    font-size: {FONT_SIZE_SMALL}px;
}}
QLabel#statusText {{ color: {p.text_muted}; font-size: {FONT_SIZE_SMALL}px; background: transparent; }}
QSplitter::handle {{ background: {p.separator}; width: 1px; }}

/* ----- icon buttons ----- */
QToolButton {{
    background: transparent;
    border: none;
    border-radius: {RADIUS_SMALL}px;
    padding: {space(1)}px;
    min-width: {ICON_MEDIUM}px;
    min-height: {ICON_MEDIUM}px;
}}
QToolButton:hover {{ background: {p.hover}; }}
QToolButton:pressed {{ background: {p.selected}; }}
QToolButton:focus {{ outline: none; border: 2px solid {p.accent}; }}
QToolButton::menu-indicator {{ image: none; width: 0px; }}
QToolButton#speedButton {{ padding-right: {space(1)}px; }}
QSpinBox {{ min-width: {space(6)}px; }}
QToolButton#playButton {{
    background: {p.accent};
    border-radius: {PLAY_BUTTON_SIZE // 2}px;
    min-width: {PLAY_BUTTON_SIZE}px; max-width: {PLAY_BUTTON_SIZE}px;
    min-height: {PLAY_BUTTON_SIZE}px; max-height: {PLAY_BUTTON_SIZE}px;
    padding: 0px;
}}
QToolButton#playButton:hover {{ background: {p.accent_hover}; }}
QToolButton#playButton:pressed {{ background: {p.accent_pressed}; }}
QToolButton#playButton:disabled {{ background: {p.progress_track}; }}
QToolButton#playButton:focus {{ border: 2px solid {p.text}; }}

/* ----- primary (text) button ----- */
QPushButton#primaryButton {{
    background: {p.accent};
    color: {p.on_accent};
    border: none;
    border-radius: {RADIUS_MEDIUM}px;
    padding: {space(1.5)}px {space(3)}px;
    font-size: {FONT_SIZE_LABEL}px;
    font-weight: 600;
}}
QPushButton#primaryButton:hover {{ background: {p.accent_hover}; }}
QPushButton#primaryButton:pressed {{ background: {p.accent_pressed}; }}
QPushButton#primaryButton:focus {{ outline: none; border: 2px solid {p.text}; }}

/* ----- dialogs keep ordinary buttons readable in both themes ----- */
QDialog, QMessageBox {{ background: {p.background}; }}
QDialog QPushButton, QMessageBox QPushButton {{
    background: {p.surface};
    border: 1px solid {p.separator};
    border-radius: {RADIUS_SMALL}px;
    padding: {space(0.75)}px {space(2)}px;
    min-width: {space(10)}px;
}}
QDialog QPushButton:hover, QMessageBox QPushButton:hover {{ background: {p.hover}; }}
QDialog QPushButton:default, QMessageBox QPushButton:default {{
    background: {p.accent}; color: {p.on_accent}; border: none;
}}
QRadioButton, QCheckBox {{ spacing: {space(1)}px; }}

/* ----- inputs ----- */
QSpinBox, QComboBox {{
    background: {p.background};
    border: 1px solid {p.separator};
    border-radius: {RADIUS_SMALL}px;
    padding: {space(0.5)}px {space(1)}px;
    min-height: {space(3)}px;
}}
QSpinBox:focus, QComboBox:focus {{ border: 1px solid {p.accent}; }}
QComboBox::drop-down {{ border: none; width: {space(2.5)}px; }}
QComboBox QAbstractItemView {{
    background: {p.background};
    border: 1px solid {p.separator};
    selection-background-color: {p.selected};
    selection-color: {p.text};
    outline: none;
}}
QProgressDialog QProgressBar, QProgressBar {{
    background: {p.progress_track};
    border: none;
    border-radius: {PROGRESS_BAR_HEIGHT // 2 + 1}px;
    max-height: {PROGRESS_BAR_HEIGHT}px;
    min-height: {PROGRESS_BAR_HEIGHT}px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{ background: {p.accent}; border-radius: {PROGRESS_BAR_HEIGHT // 2 + 1}px; }}
QProgressDialog QProgressBar {{ max-height: {space(1)}px; min-height: {space(1)}px; }}

/* ----- scrollbars ----- */
QScrollBar:vertical {{ background: transparent; width: {space(1.25)}px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: {p.separator}; border-radius: {space(0.5)}px; min-height: {space(4)}px;
}}
QScrollBar::handle:vertical:hover {{ background: {p.text_disabled}; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
    background: none; height: 0; width: 0;
}}

/* ----- sidebar ----- */
QWidget#sidebar {{ background: {p.sidebar}; }}
QWidget#sidebar QLabel#sidebarHeading {{
    color: {p.text_muted};
    font-size: {FONT_SIZE_SMALL}px;
    font-weight: 600;
    letter-spacing: 1px;
}}
QWidget#sidebar QLabel#emptyLibrary {{ color: {p.text_muted}; }}
QListWidget#bookList {{ background: transparent; border: none; outline: none; }}
QListWidget#bookList::item {{
    background: transparent;
    border-radius: {RADIUS_MEDIUM}px;
    margin: {space(0.25)}px 0;
}}
QListWidget#bookList::item:hover {{ background: {p.hover}; }}
QListWidget#bookList::item:selected {{ background: {p.selected}; }}
QWidget#bookRow {{ background: transparent; }}
QLabel#bookTitle {{ font-weight: 600; background: transparent; }}
QLabel#bookTitle[current="true"] {{ color: {p.accent}; }}
QLabel#bookProgressLabel {{ color: {p.text_muted}; font-size: {FONT_SIZE_SMALL}px; background: transparent; }}
QWidget#sidebarFooter {{ border-top: 1px solid {p.separator}; background: {p.sidebar}; }}

/* ----- home page ----- */
QLabel#homeTitle {{
    font-size: {FONT_SIZE_TITLE}px;
    font-weight: 600;
    color: {p.text};
    letter-spacing: -0.5px;
}}
QLabel#homeTagline {{ color: {p.text_muted}; font-size: {FONT_SIZE_LABEL}px; }}
QFrame#dropZone {{
    background: {p.surface};
    border: 2px dashed {p.text_disabled};
    border-radius: {RADIUS_LARGE}px;
}}
QFrame#dropZone[dragActive="true"] {{
    background: {p.accent_soft};
    border: 2px dashed {p.accent};
}}
QLabel#dropTitle {{ font-size: {FONT_SIZE_LARGE}px; font-weight: 500; background: transparent; }}
QLabel#dropHint {{ color: {p.text_muted}; background: transparent; }}
QFrame#errorBanner {{
    background: {p.error_background};
    border-radius: {RADIUS_MEDIUM}px;
}}
QLabel#errorText {{ color: {p.error_text}; font-weight: 500; background: transparent; }}
QLabel#errorIcon {{ background: transparent; }}

/* ----- reader ----- */
QLabel#sectionTitle {{ color: {p.text_muted}; font-size: {FONT_SIZE_SMALL}px; font-weight: 600; letter-spacing: 1px; }}
QLabel#bookHeading {{ font-size: {FONT_SIZE_LARGE}px; font-weight: 600; }}
QTextEdit#readerText {{
    background: {p.background};
    border: none;
    font-family: "{FONT_READING}";
    font-size: {FONT_SIZE_READING}px;
    color: {p.text};
    selection-background-color: {p.highlight};
    selection-color: {p.highlight_text};
}}

/* ----- player bar ----- */
QFrame#playerBar {{
    background: {p.surface};
    border-top: 1px solid {p.separator};
}}
QLabel#playerLabel {{ color: {p.text_muted}; font-size: {FONT_SIZE_BODY}px; font-weight: 500; background: transparent; }}
QLabel#positionLabel {{ color: {p.text}; font-size: {FONT_SIZE_SMALL}px; font-weight: 500; background: transparent; }}
"""
