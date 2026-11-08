"""Tests for the design tokens: identical palettes, the fixed accent and WCAG contrast."""

from __future__ import annotations

import re
from dataclasses import asdict

import pytest

from vocalpages import theme
from vocalpages.theme import DARK, LIGHT, NON_TEXT_PAIRS, PALETTES, TEXT_PAIRS, contrast_ratio

HEX = re.compile(r"^#[0-9A-F]{6}$")


def test_palettes_define_exactly_the_same_tokens() -> None:
    light, dark = asdict(LIGHT), asdict(DARK)
    assert light.keys() == dark.keys()
    assert set(theme.token_names()) == set(light) - {"name"}


@pytest.mark.parametrize("palette", PALETTES.values(), ids=PALETTES.keys())
def test_every_token_is_an_uppercase_hex_color(palette: theme.Palette) -> None:
    for token in theme.token_names():
        assert HEX.match(getattr(palette, token)), token


def test_light_accent_is_exactly_the_brand_wine() -> None:
    assert LIGHT.accent == "#722F37"


def test_dark_highlight_uses_the_brand_wine() -> None:
    assert DARK.highlight == "#722F37"


@pytest.mark.parametrize("palette", PALETTES.values(), ids=PALETTES.keys())
@pytest.mark.parametrize("fg,bg", TEXT_PAIRS)
def test_text_meets_wcag_aa(palette: theme.Palette, fg: str, bg: str) -> None:
    ratio = contrast_ratio(getattr(palette, fg), getattr(palette, bg))
    assert ratio >= 4.5, f"{palette.name}: {fg} on {bg} is {ratio:.2f}:1"


@pytest.mark.parametrize("palette", PALETTES.values(), ids=PALETTES.keys())
@pytest.mark.parametrize("fg,bg", NON_TEXT_PAIRS)
def test_icons_and_ui_parts_meet_wcag_aa(palette: theme.Palette, fg: str, bg: str) -> None:
    ratio = contrast_ratio(getattr(palette, fg), getattr(palette, bg))
    assert ratio >= 3.0, f"{palette.name}: {fg} on {bg} is {ratio:.2f}:1"


def test_contrast_ratio_reference_values() -> None:
    assert contrast_ratio("#000000", "#FFFFFF") == pytest.approx(21.0)
    assert contrast_ratio("#777777", "#777777") == pytest.approx(1.0)


@pytest.mark.parametrize("palette", PALETTES.values(), ids=PALETTES.keys())
def test_stylesheet_uses_only_palette_colors(palette: theme.Palette) -> None:
    sheet = theme.build_stylesheet(palette)
    used = set(re.findall(r"#[0-9A-Fa-f]{6}\b", sheet))
    allowed = {getattr(palette, t) for t in theme.token_names()}
    assert used <= allowed


def test_spacing_is_on_the_8px_grid() -> None:
    assert theme.space(1) == 8
    assert theme.space(2) == 16
    assert theme.GRID == 8


def test_bundled_fonts_and_licenses_exist() -> None:
    fonts = theme.FONTS_DIR
    assert sorted(p.name for p in fonts.glob("inter/*.ttf"))
    assert sorted(p.name for p in fonts.glob("literata/*.ttf"))
    assert (fonts / "inter" / "LICENSE.txt").is_file()
    assert (fonts / "literata" / "OFL.txt").is_file()
