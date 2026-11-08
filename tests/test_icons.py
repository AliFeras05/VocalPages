"""Tests for themed SVG icons."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6.QtSvg")

from PySide6.QtGui import QColor, QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication, QToolButton  # noqa: E402

from vocalpages.icons import ICONS_DIR, IconSet, render_pixmap  # noqa: E402
from vocalpages.theme import DARK, LIGHT  # noqa: E402

USED_ICONS = [
    "play", "pause", "square", "skip-back", "skip-forward", "folder-open", "file-up", "download",
    "house", "trash-2", "gauge", "sun", "moon", "circle-alert", "corner-down-left",
]


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _dominant_color(pixmap) -> QColor:  # noqa: ANN001
    image = pixmap.toImage()
    for y in range(image.height()):
        for x in range(image.width()):
            color = image.pixelColor(x, y)
            if color.alpha() == 255:
                return color
    raise AssertionError("icon rendered fully transparent")


def test_all_used_icons_are_bundled_with_license() -> None:
    for name in USED_ICONS:
        assert (ICONS_DIR / f"{name}.svg").is_file(), name
    assert (ICONS_DIR / "LICENSE").is_file()


def test_icon_is_tinted_with_requested_color(app: QApplication) -> None:
    pixmap = render_pixmap("square", "#722F37", 48)
    assert _dominant_color(pixmap).name().upper() == "#722F37"


def test_bound_button_is_retinted_on_theme_change(app: QApplication) -> None:
    icons = IconSet(LIGHT)
    button = QToolButton()
    icons.bind(button, "square")
    light = _dominant_color(button.icon().pixmap(48, 48, QIcon.Mode.Normal)).name().upper()
    icons.set_palette(DARK)
    dark = _dominant_color(button.icon().pixmap(48, 48, QIcon.Mode.Normal)).name().upper()
    assert light == LIGHT.icon
    assert dark == DARK.icon


def test_disabled_and_hover_states_use_theme_tokens(app: QApplication) -> None:
    icon = IconSet(LIGHT).icon("square", size=48)
    hover = _dominant_color(icon.pixmap(48, 48, QIcon.Mode.Active)).name().upper()
    disabled = _dominant_color(icon.pixmap(48, 48, QIcon.Mode.Disabled)).name().upper()
    assert hover == LIGHT.accent
    assert disabled == LIGHT.icon_disabled


def test_rebinding_replaces_icon(app: QApplication) -> None:
    icons = IconSet(LIGHT)
    button = QToolButton()
    icons.bind(button, "play")
    icons.bind(button, "pause")
    assert len(icons._bindings) == 1
