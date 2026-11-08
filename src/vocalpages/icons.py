"""Lucide SVG icons, tinted with the current theme's colors.

The SVGs ship in ``assets/icons`` (ISC license, see the LICENSE file there) and
use ``stroke="currentColor"``; each one is rendered with the palette color for
its state (normal, hover, disabled). Buttons and actions bound through
``IconSet.bind`` are re-tinted automatically when the theme changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import shiboken6
from PySide6.QtCore import QByteArray, QObject, QRectF, QSize, Qt
from PySide6.QtGui import QAction, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QAbstractButton, QLabel

from vocalpages.theme import ICON_MEDIUM, Palette

ICONS_DIR = Path(__file__).resolve().parent / "assets" / "icons"

# Which palette tokens tint an icon in each state, per role.
ROLES: dict[str, tuple[str, str, str]] = {
    # role: (normal, hover/active, disabled)
    "default": ("icon", "accent", "icon_disabled"),
    "on_accent": ("on_accent", "on_accent", "icon_disabled"),
    "accent": ("accent", "accent_hover", "icon_disabled"),
    "error": ("error_text", "error_text", "error_text"),
}


@lru_cache(maxsize=None)
def _svg_source(name: str) -> str:
    path = ICONS_DIR / f"{name}.svg"
    if not path.is_file():
        raise FileNotFoundError(f"Unknown icon: {name}")
    return path.read_text(encoding="utf-8")


def render_pixmap(name: str, color: str, size: int, device_pixel_ratio: float = 1.0) -> QPixmap:
    """Render the named icon at ``size`` logical pixels in ``color``."""
    svg = _svg_source(name).replace("currentColor", color)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    physical = max(1, round(size * device_pixel_ratio))
    pixmap = QPixmap(physical, physical)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, physical, physical))
    painter.end()
    pixmap.setDevicePixelRatio(device_pixel_ratio)
    return pixmap


@dataclass
class _Binding:
    target: QAction | QAbstractButton | QLabel
    name: str
    role: str
    size: int


class IconSet(QObject):
    """Creates themed icons and keeps bound widgets in sync with the palette."""

    def __init__(self, palette: Palette, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._palette = palette
        self._bindings: list[_Binding] = []

    @property
    def palette(self) -> Palette:
        """The palette icons are currently tinted with."""
        return self._palette

    def icon(self, name: str, role: str = "default", size: int = ICON_MEDIUM) -> QIcon:
        """Return a QIcon with normal, hover (Active) and disabled pixmaps."""
        normal, hover, disabled = (getattr(self._palette, token) for token in ROLES[role])
        ratio = _device_pixel_ratio()
        icon = QIcon()
        for mode, color in (
            (QIcon.Mode.Normal, normal),
            (QIcon.Mode.Active, hover),
            (QIcon.Mode.Selected, hover),
            (QIcon.Mode.Disabled, disabled),
        ):
            icon.addPixmap(render_pixmap(name, color, size, ratio), mode)
        return icon

    def bind(
        self, target: QAction | QAbstractButton | QLabel, name: str, role: str = "default",
        size: int = ICON_MEDIUM,
    ) -> None:
        """Give ``target`` the named icon now and re-tint it on every theme change.

        Binding the same target again (e.g. play -> pause) replaces its icon.
        """
        self._bindings = [b for b in self._bindings if b.target is not target and shiboken6.isValid(b.target)]
        binding = _Binding(target, name, role, size)
        self._bindings.append(binding)
        self._apply(binding)

    def set_palette(self, palette: Palette) -> None:
        """Switch palettes and re-tint every bound icon."""
        self._palette = palette
        self._bindings = [b for b in self._bindings if shiboken6.isValid(b.target)]
        for binding in self._bindings:
            self._apply(binding)

    def _apply(self, binding: _Binding) -> None:
        target = binding.target
        if isinstance(target, QLabel):
            color = getattr(self._palette, ROLES[binding.role][0])
            target.setPixmap(render_pixmap(binding.name, color, binding.size, _device_pixel_ratio()))
            return
        target.setIcon(self.icon(binding.name, binding.role, binding.size))
        if isinstance(target, QAbstractButton):
            target.setIconSize(QSize(binding.size, binding.size))


def _device_pixel_ratio() -> float:
    screen = QGuiApplication.primaryScreen()
    return screen.devicePixelRatio() if screen is not None else 1.0
