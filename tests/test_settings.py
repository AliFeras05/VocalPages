"""Tests for the saved theme setting and the startup theme choice."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from vocalpages.settings import Settings, initial_theme


def test_theme_is_unset_until_chosen(tmp_path: Path) -> None:
    settings = Settings(tmp_path)
    assert settings.theme is None
    assert not settings.path.exists()


def test_theme_choice_is_saved_and_restored(tmp_path: Path) -> None:
    Settings(tmp_path).theme = "dark"
    assert Settings(tmp_path).theme == "dark"
    Settings(tmp_path).theme = "light"
    assert Settings(tmp_path).theme == "light"


def test_unknown_theme_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        Settings(tmp_path).theme = "purple"


def test_corrupt_settings_fall_back_to_defaults(tmp_path: Path) -> None:
    (tmp_path / "settings.json").write_text("{nope")
    assert Settings(tmp_path).theme is None


@pytest.mark.parametrize(
    "saved,system_dark,expected",
    [
        (None, None, "light"),  # OS unknown -> light
        (None, True, "dark"),  # follow the OS
        (None, False, "light"),
        ("light", True, "light"),  # the user's choice wins over the OS
        ("dark", False, "dark"),
    ],
)
def test_initial_theme(saved: str | None, system_dark: bool | None, expected: str) -> None:
    assert initial_theme(saved, system_dark) == expected


class _SilentEngine:
    is_loaded = True

    def load(self) -> None:
        pass

    def synthesize(self, text: str, speed: float = 1.0) -> np.ndarray:
        return np.zeros(240, dtype=np.float32)


def test_toggle_switches_theme_and_survives_restart(tmp_path: Path) -> None:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from vocalpages import theme
    from vocalpages.gui import MainWindow
    from vocalpages.library import Library

    window = MainWindow(engine=_SilentEngine(), library=Library(tmp_path, legacy_dirs=[]))
    first = window.theme_name
    window.toggle_theme()
    second = window.theme_name
    assert second != first
    assert app.styleSheet() == theme.build_stylesheet(theme.PALETTES[second])
    expected_tip = "Switch to light theme" if second == "dark" else "Switch to dark theme"
    assert window.theme_button.toolTip() == expected_tip
    assert window.theme_button.accessibleName() == expected_tip
    window.close()

    reopened = MainWindow(engine=_SilentEngine(), library=Library(tmp_path, legacy_dirs=[]))
    assert reopened.theme_name == second
    reopened.close()
