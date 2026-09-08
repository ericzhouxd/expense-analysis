"""Shared visual components. Pure markup helpers never query private data."""

from __future__ import annotations

import html
from pathlib import Path

import streamlit as st

ASSETS = Path(__file__).parent / "assets"


def inject_theme() -> None:
    st.html(ASSETS / "theme.css")
    # Trusted, static code only. Tracks the native theme without reading data or
    # changing Streamlit preferences. Never interpolate user content here.
    st.html(ASSETS / "theme_bridge.html", unsafe_allow_javascript=True)


def currency(cents: int) -> str:
    return f"{'−' if cents < 0 else ''}${abs(cents) / 100:,.2f}"


def summary_markup(rows: list[tuple[str, str]], *, title: str = "Budget summary") -> str:
    body = "".join(
        f'<div class="summary-row"><dt>{html.escape(label)}</dt>'
        f'<dd class="numeric">{html.escape(value)}</dd></div>'
        for label, value in rows
    )
    return (
        '<section class="summary-window"><h2 class="window-title">'
        f'{html.escape(title)}</h2><dl class="summary-ledger">{body}</dl></section>'
    )


def budget_hero_markup(period: dict) -> str:
    remaining = period["remaining"]
    label = "Left to spend" if remaining >= 0 else "Over allowance"
    state = "over-budget" if remaining < 0 else ""
    # The mark is decorative, vector-native, and doesn't introduce image requests.
    orbit = """<svg class="chrome-orbit" viewBox="0 0 140 100" aria-hidden="true">
        <defs><linearGradient id="orbit-metal" x1="0" y1="0" x2="1" y2="1">
        <stop stop-color="#fafafa"/><stop offset=".22" stop-color="#71766c"/>
        <stop offset=".4" stop-color="#ffffff"/><stop offset=".6" stop-color="#30342c"/>
        <stop offset=".83" stop-color="#e8eae4"/><stop offset="1" stop-color="#8b9185"/>
        </linearGradient></defs>
        <ellipse cx="70" cy="48" rx="58" ry="23" transform="rotate(-28 70 48)"
         fill="none" stroke="#52584b" stroke-width="10"/>
        <ellipse cx="70" cy="48" rx="58" ry="23" transform="rotate(-28 70 48)"
         fill="none" stroke="url(#orbit-metal)" stroke-width="7"/>
        <path d="M93 28 L128 32 L110 62 Z" fill="url(#orbit-metal)" stroke="#505548"/>
        </svg>"""
    rows = [
        ("Period target", currency(period["target"])),
        ("Committed · paid + reserved", currency(period["reserved"])),
        ("Protected buffer", currency(period["buffer"])),
        ("Everyday allowance · smoothed", currency(period["allowance"])),
        ("Everyday spent", currency(period["flexible_spent"])),
    ]
    return (
        '<div class="budget-top-grid">'
        f'<section class="balance-panel {state}" aria-label="{label}">'
        f'<h2>{label}</h2><div class="balance-value numeric">{currency(abs(remaining))}</div>'
        "<p>After bills and buffer. Not a cash balance.</p>"
        f"{orbit}</section>{summary_markup(rows)}</div>"
    )


def usage_markup(spent: int, available: int) -> str:
    """Keep the financial ratio unbounded; clamp only the visual meter."""
    if available <= 0:
        return '<p class="usage-note">No positive everyday allowance for this period.</p>'
    ratio = spent / available
    width = min(max(ratio * 100, 0), 100)
    state = "over" if ratio > 1 else ""
    return (
        f'<div class="usage-window {state}"><div class="usage-label">'
        f"<span>{currency(spent)} / {currency(available)}</span>"
        f'<span><b class="numeric">{ratio:.0%}</b> used</span></div>'
        f'<div class="segmented-meter" role="meter" aria-label="Everyday allowance used" '
        f'aria-valuemin="0" aria-valuemax="100" aria-valuenow="{width:.2f}" '
        f'aria-valuetext="{ratio:.0%} used"><span style="width:{width:.4f}%"></span>'
        "</div></div>"
    )
