"""Contrast budgets for the shared native, custom, and chart palettes."""

import re
import tomllib
from pathlib import Path

import pytest

from expense_analysis.ui.theme import PALETTE, SAGE

ROOT = Path(__file__).resolve().parents[1]


def contrast(first, second):
    def luminance(color):
        channels = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        return sum(
            (v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4) * weight
            for v, weight in zip(channels, (0.2126, 0.7152, 0.0722), strict=True)
        )

    values = [luminance(first), luminance(second)]
    return (max(values) + 0.05) / (min(values) + 0.05)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_theme_text_and_chart_contrast(theme):
    native = tomllib.loads((ROOT / ".streamlit/config.toml").read_text())["theme"][theme]
    css = (ROOT / "src/expense_analysis/assets/theme.css").read_text()
    base = re.search(r":root\s*\{([^}]+)\}", css)
    assert base, "Missing base theme colors"
    tokens = dict(re.findall(r"--([\w-]+):\s*(#[\da-fA-F]{6})", base[1]))
    if theme == "dark":
        dark = re.search(r""":root\[data-jizhang-theme=['"]dark['"]\]\s*\{([^}]+)\}""", css)
        assert dark, "Missing dark theme colors"
        tokens.update(re.findall(r"--([\w-]+):\s*(#[\da-fA-F]{6})", dark[1]))
    for foreground in ("ink", "muted"):
        for background in (tokens["panel"], native["backgroundColor"]):
            assert contrast(tokens[foreground], background) >= 4.5
    for background in ("metal-low", "metal-high"):
        assert contrast(tokens["ink"], tokens[background]) >= 4.5
    for status in ("positive", "negative", "warning"):
        assert contrast(tokens[status], tokens["panel"]) >= 4.5
    for status in ("blue", "green", "yellow", "red"):
        assert contrast(native[f"{status}TextColor"], native[f"{status}BackgroundColor"]) >= 4.5
    for background in ("backgroundColor", "secondaryBackgroundColor"):
        assert contrast(native["textColor"], native[background]) >= 4.5
        assert contrast(native["linkColor"], native[background]) >= 4.5
    # Chart marks are non-text graphics. Labels inherit the theme text separately.
    for color in (*PALETTE, SAGE):
        assert contrast(color, tokens["panel"]) >= 3
