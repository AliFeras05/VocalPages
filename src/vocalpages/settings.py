"""Small user settings (currently only the theme choice), stored in app data.

The file is written only after the user changes a setting; until then the app
follows the operating system's light/dark preference.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

SETTINGS_FILE = "settings.json"
THEMES = ("light", "dark")
DEFAULT_THEME = "light"


class Settings:
    """JSON-backed settings in ``data_dir/settings.json``."""

    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / SETTINGS_FILE
        self._data = self._load()

    def _load(self) -> dict[str, object]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            log.warning("Settings file is unreadable; using defaults")
            return {}
        return data if isinstance(data, dict) else {}

    @property
    def theme(self) -> str | None:
        """The theme the user chose with the toggle, or None if they never did."""
        value = self._data.get("theme")
        return value if value in THEMES else None

    @theme.setter
    def theme(self, value: str) -> None:
        if value not in THEMES:
            raise ValueError(f"Unknown theme: {value}")
        self._data["theme"] = value
        self._save()

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            log.warning("Could not save settings")


def initial_theme(saved: str | None, system_is_dark: bool | None) -> str:
    """Pick the theme at startup: the saved choice, else the OS setting, else light."""
    if saved in THEMES:
        return saved
    if system_is_dark is None:
        return DEFAULT_THEME
    return "dark" if system_is_dark else "light"


def system_prefers_dark() -> bool | None:
    """True/False if Qt reports the OS color scheme, None if it is unknown."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication

    hints = QGuiApplication.styleHints()
    scheme = hints.colorScheme() if hasattr(hints, "colorScheme") else Qt.ColorScheme.Unknown
    if scheme == Qt.ColorScheme.Dark:
        return True
    if scheme == Qt.ColorScheme.Light:
        return False
    return None
