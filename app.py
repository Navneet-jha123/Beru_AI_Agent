"""BERU — friendly UI for the original Streamlit app (v2: readable in any Streamlit theme).

Place this file beside the EXISTING agent.py, config.py, forge.py, modes/,
proactive_daemon.py and tools_registry.py. Start with: streamlit run app.py
Also copy config.toml to  .streamlit/config.toml  (recommended, see notes).

What changed from v1
  * Every color now comes from one palette (light or dark). Text, inputs,
    dropdowns, expanders, chat bubbles, alerts and code no longer depend on the
    browser/Streamlit theme, so nothing turns white-on-white or black-on-black.
  * Navigation and the Light/Dark switch are real buttons (no hidden radio
    circles).
  * Sending a message first switches to the conversation layout, then runs the
    agent, so the home-screen cards no longer stay between chat bubbles.
  * The chat box is disabled while BERU works; a failed or interrupted request
    shows details and a manual "Try again" button (nothing is retried
    automatically because tools can have side effects).

Backend imports, mode identifiers, quick-action prompts and every backend call
signature are unchanged. No new third-party dependency is required.
"""
from __future__ import annotations

import inspect
import json
import os
import time
import uuid
from html import escape
from pathlib import Path
from typing import Any, Callable

import psutil
import streamlit as st

# Original integration boundary: keep these project modules unchanged.
from agent import run_agent
from config import PRIMARY_MODEL, GEMINI_MODEL, TRACES_DIR, WORKSPACE_DIR
from feedback import (
    get_feedback_summary,
    has_answer_feedback,
    record_answer_feedback,
    set_response_style_preference,
)
from forge import ACTIVE_FORGED_TOOLS, forge_new_tool
from modes.developer import compile_to_exe, run_dev_command, run_test_suite
from modes.hacker import (
    audit_ports_and_services,
    audit_security_headers,
    deep_dns_recon,
    inspect_ssl_certificate,
)
from modes.tester import audit_code_security
from proactive_daemon import generate_system_health_briefing
from tools_registry import get_live_schemas, get_live_tools
from brain import get_tool_optimizer_report
from modes import market_analyst as market_core

import api_keys  # per-visitor API keys (bring your own keys)
import key_ui

st.set_page_config(
    page_title="BERU · Your everyday AI workspace",
    page_icon="✦",
    layout="wide",
    initial_sidebar_state="expanded",
)

QUICK_PROMPTS = {'computer': 'Run full system diagnostic: check CPU, memory, disk, and active processes.',
 'code': 'Perform comprehensive static security audit on modes/developer.py.',
 'website': 'Perform complete ethical OSINT recon on scanme.nmap.org (DNS, SSL, and ports).',
 'market': "Use BERU's market_data_status, then ask only for the company/stock name (unless the user "
           'already gave it). Call analyze_stock_by_name to resolve one company and fetch daily candles '
           '(plus 5-minute candles only if the configured provider supports them), or call '
           'screen_stock_watchlist to compare a user-provided list of up to 20 tickers using '
           'transparent daily technical evidence. If a name maps to multiple listings, show matches and '
           'ask which one. If market_data_status reports Alpha Vantage, explain it provides '
           'daily/weekly history here and no free intraday feed; if no provider is configured, explain '
           'CSV fallback. If the user gives an as-of date or asks for a historical forecast test, pass '
           'that date to as_of on analyze_stock_by_name or analyze_stock_market so later candles are '
           'excluded. Label historical analog frequencies as uncalibrated sample frequencies, not '
           'reliable probabilities. Give a constructive/mixed/weak setup summary and evidence, never a '
           'personalized buy/sell instruction. Do not invent current prices or participant counts.'}

DEFAULT_TOOL_CODE = 'import urllib.parse\ndef generate_qr_code(text: str, filename: str = "qr.png") -> str:\n    url = f"https://api.qrserver.com/v1/create-qr-code/?size=250x250&data={urllib.parse.quote(text)}"\n    return f"QR Code generated! Access at: {url}"\n'

MODE_LABELS = {
    "General": "Everyday help",
    "Developer": "Writing & building code",
    "Tester": "Code quality & testing",
    "Hacker": "Security research",
    "Medical": "Diagnostic Assistant (Local)",
    "Reverse Engineering": "Offline static binary analysis",
    "Sports": "Sports analytics (Local)",
    "Data Analyst": "Private spreadsheet & SQL analysis",
    "API": "Private OpenAPI connector",
}
MODE_HINTS = {
    "General": "A good place to start. Ask naturally, without special commands.",
    "Developer": "Help with code, development tasks and building applications.",
    "Tester": "Help checking code quality, finding issues and testing your work.",
    "Hacker": "Research websites and systems you own or are authorized to assess.",
    "Medical": "Lab extraction and simple calculations run locally. This is not diagnosis or medical advice.",
    "Reverse Engineering": "Inspect bounded files locally. Samples are never executed by these analysis tools.",
    "Sports": "Local calculators for Elo, form, win rate. Free-tier fetchers for live scores. Not betting advice.",
    "Data Analyst": "Profile local CSVs, then run read-only CSV, SQLite and Excel analysis.",
    "API": "Connect to reviewed OpenAPI operations on explicitly allowlisted hosts using your local model.",
}
PAGES = ["Assistant", "Stock explorer", "Create tools", "Developer workspace", "Website checks", "Activity history"]
NAV_LABELS = {
    "Assistant": "✦  Assistant",
    "Stock explorer": "↗  Stock explorer",
    "Create tools": "⊞  Create tools",
    "Developer workspace": "⌘  Developer workspace",
    "Website checks": "◎  Website checks",
    "Activity history": "◷  Activity history",
}
INTERVAL_LABELS = {
    "1d": "Daily", "1wk": "Weekly", "5m": "Every 5 minutes",
    "15m": "Every 15 minutes", "1h": "Hourly",
}

# ---------------------------------------------------------------------------
# Theme: ONE palette per appearance. Every rule below reads these variables.
# Text/background pairs were chosen for >= 4.5:1 contrast.
# ---------------------------------------------------------------------------
LIGHT = {
    "bg": "#f6f7fb", "surface": "#ffffff", "surface2": "#f4f2fb", "sidebar": "#eef0f8",
    "text": "#1f2236", "muted": "#596279", "line": "#e1e4ee", "line2": "#cdd2e2",
    "accent": "#6a4bd1", "btn": "#6a4bd1", "btn2": "#5836bd", "on-btn": "#ffffff",
    "tint": "#eee9fb", "tint-text": "#4d34a6", "hover": "#e4e6f2",
    "nav-bg": "#e2dbf7", "nav-text": "#4a31a3", "input": "#ffffff", "seg": "#e1e3ef",
    "user-bg": "#efebfb", "user-line": "#e0d9f5",
    "code-bg": "#1c2133", "code-text": "#e9e8f5", "icode-bg": "#ece8f9", "icode-text": "#4b34a0",
    "focus": "#7f66d8", "shadow": "rgba(40,36,90,.08)", "glow": "rgba(150,124,230,.28)",
    "track": "#e1e3ee", "fill": "#8268d6", "empty": "rgba(255,255,255,.7)",
    "icon-bg": "#eee9f9", "icon-fg": "#6247b8", "mint-bg": "#e5f3ee", "mint-fg": "#2f6f5a",
    "blue-bg": "#e8effb", "blue-fg": "#3f66b0", "peach-bg": "#fbeee2", "peach-fg": "#9a6226",
    "av-user-bg": "#e3daf7", "av-user-fg": "#5f45a6", "av-ai-bg": "#e1f1ea", "av-ai-fg": "#2f6f5a",
    "alert": "#f1eefb", "placeholder": "#6f778c", "pill-bg": "#efebf9", "pill-line": "#e0d9f3",
    "pill-text": "#5b40a6", "popover": "#ffffff",
}
DARK = {
    "bg": "#0f1321", "surface": "#1a2033", "surface2": "#202741", "sidebar": "#141a2b",
    "text": "#f1effb", "muted": "#aab3c9", "line": "#323a52", "line2": "#4a5370",
    "accent": "#bba8ff", "btn": "#7a59dc", "btn2": "#8a6cea", "on-btn": "#ffffff",
    "tint": "#2e2748", "tint-text": "#dccfff", "hover": "#252c44",
    "nav-bg": "#35294f", "nav-text": "#e0d5ff", "input": "#222a41", "seg": "#0d111f",
    "user-bg": "#28243e", "user-line": "#473e63",
    "code-bg": "#11152a", "code-text": "#e9e8f5", "icode-bg": "#2e2a49", "icode-text": "#dccfff",
    "focus": "#b19af2", "shadow": "rgba(0,0,0,.4)", "glow": "rgba(124,92,200,.30)",
    "track": "#343a50", "fill": "#a98ff0", "empty": "rgba(26,32,51,.6)",
    "icon-bg": "#3a2f55", "icon-fg": "#dcccff", "mint-bg": "#23403a", "mint-fg": "#a9e2cb",
    "blue-bg": "#25344f", "blue-fg": "#a8c6f7", "peach-bg": "#483529", "peach-fg": "#efc399",
    "av-user-bg": "#3d315c", "av-user-fg": "#e1d1ff", "av-ai-bg": "#244338", "av-ai-fg": "#b6ecd3",
    "alert": "#262040", "placeholder": "#98a2ba", "pill-bg": "#2d2646", "pill-line": "#4a3f69",
    "pill-text": "#dacfff", "popover": "#232a40",
}

# Static rules. No colors are hard-coded here: only var(--b-*).
# IMPORTANT: no blank lines inside this string (Markdown would end the <style> block).
BASE_CSS = """
:root { --b-font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif; }
html, body, .stApp, [data-testid="stApp"], [data-testid="stAppViewContainer"], [data-testid="stMain"] {
  background: var(--b-bg) !important; color: var(--b-text) !important;
}
.stApp { font-family: var(--b-font); }
.stApp :is(p, label, input, textarea, button, select, li, summary, h1, h2, h3, h4) { font-family: var(--b-font); }
.stApp :is(h1, h2, h3, h4) { color: var(--b-text) !important; letter-spacing: -.03em; font-weight: 650; text-transform: none; }
.stApp h3 { font-size: 1.15rem; }
[data-testid="stHeader"] { background: transparent !important; }
[data-testid="stToolbar"], [data-testid="stToolbar"] :is(button, a, span, p),
[data-testid="stSidebarCollapseButton"] *, [data-testid="stExpandSidebarButton"] * { color: var(--b-muted) !important; }
[data-testid="stToolbar"] svg, [data-testid="stSidebarCollapseButton"] svg, [data-testid="stExpandSidebarButton"] svg { fill: var(--b-muted) !important; }
[data-testid="stMainBlockContainer"], .main .block-container { max-width: 1240px; padding: 3.2rem 3.2rem 5rem; }
/* ---------- Sidebar ---------- */
[data-testid="stSidebar"], [data-testid="stSidebar"] > div:first-child { background: var(--b-sidebar) !important; }
[data-testid="stSidebar"] { border-right: 1px solid var(--b-line); min-width: 260px; }
[data-testid="stSidebarUserContent"] { padding: 1rem 1.2rem 1.8rem; }
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: .7rem; }
.b-brand { display: flex; gap: 11px; align-items: center; padding: 0 3px 18px; }
.b-brandmark { display: grid; place-items: center; width: 41px; height: 41px; flex-shrink: 0; color: #fff;
  background: linear-gradient(140deg, #9e86f0, #6c50cf); box-shadow: 0 6px 15px var(--b-shadow); border-radius: 13px; }
.b-brandname { font-size: 1.65rem; font-weight: 760; letter-spacing: -.05em; line-height: 1.05; color: var(--b-text); }
.b-brandname .b-dot { color: var(--b-accent); }
.b-brandline { font-size: .68rem; letter-spacing: .02em; color: var(--b-muted); margin-top: 5px; }
.b-nav-label, .b-theme-label { font-size: .66rem; font-weight: 700; letter-spacing: .12em; color: var(--b-muted); margin: 6px 0 2px 6px; }
.b-sidebar-divider { border-top: 1px solid var(--b-line); margin: 14px 0 10px; }
.b-tip { background: var(--b-surface); border: 1px solid var(--b-line); border-radius: 14px; padding: 15px; margin: 8px 0 1px; }
.b-tip-title { font-size: .8rem; font-weight: 650; margin: 7px 0; color: var(--b-text); }
.b-tip p { font-size: .76rem; line-height: 1.6; color: var(--b-muted); margin: 0; }
.b-tip .b-small-spark { color: var(--b-accent); font-size: 1.1rem; }
.b-sidebar-footer { font-size: .7rem; color: var(--b-muted); padding: 10px 3px 0; }
/* Light/Dark switch (two real buttons in a keyed container) */
[data-testid="stSidebar"] .st-key-beru_themeswitch { background: var(--b-seg); border: 1px solid var(--b-line); border-radius: 14px; padding: 4px; gap: .3rem; }
.st-key-beru_themeswitch [data-testid="stHorizontalBlock"] { gap: .3rem; }
.st-key-beru_themeswitch button { min-height: 36px !important; padding: 4px 6px !important; border: 1px solid transparent !important;
  background: transparent !important; color: var(--b-muted) !important; border-radius: 10px !important; box-shadow: none !important; }
.st-key-beru_themeswitch button p { font-size: .8rem; font-weight: 600; }
.st-key-beru_themeswitch button:hover { background: var(--b-hover) !important; color: var(--b-text) !important; border-color: transparent !important; }
.st-key-beru_themeswitch button:is([kind="primary"], [data-testid="stBaseButton-primary"]),
.st-key-beru_themeswitch button:is([kind="primary"], [data-testid="stBaseButton-primary"]):hover {
  background: var(--b-surface) !important; color: var(--b-accent) !important; border-color: var(--b-line) !important; box-shadow: 0 2px 7px var(--b-shadow) !important; }
/* Navigation (real buttons; active page is the primary one) */
[data-testid="stSidebar"] .st-key-beru_navigation, [data-testid="stSidebar"] .st-key-beru_navigation [data-testid="stVerticalBlock"] { gap: .25rem; }
.st-key-beru_navigation button { justify-content: flex-start !important; min-height: 42px !important; padding: 8px 12px !important;
  background: transparent !important; color: var(--b-muted) !important; border: 1px solid transparent !important;
  border-radius: 12px !important; box-shadow: none !important; }
.st-key-beru_navigation button > div, .st-key-beru_navigation button p { width: 100%; text-align: left; justify-content: flex-start; }
.st-key-beru_navigation button p { font-size: .88rem; font-weight: 550; }
.st-key-beru_navigation button:hover { background: var(--b-hover) !important; color: var(--b-text) !important; border-color: transparent !important; }
.st-key-beru_navigation button:is([kind="primary"], [data-testid="stBaseButton-primary"]),
.st-key-beru_navigation button:is([kind="primary"], [data-testid="stBaseButton-primary"]):hover {
  background: var(--b-nav-bg) !important; color: var(--b-nav-text) !important; border-color: var(--b-line2) !important; }
.st-key-beru_navigation button:is([kind="primary"], [data-testid="stBaseButton-primary"]) p { font-weight: 700; }
/* ---------- Top bar ---------- */
.b-topbar { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 3px 0 18px; margin-bottom: 17px; border-bottom: 1px solid var(--b-line); }
.b-breadcrumb { display: flex; gap: 11px; align-items: center; font-size: .8rem; color: var(--b-muted); }
.b-breadcrumb strong { color: var(--b-text); font-weight: 650; }
.b-slash { color: var(--b-line2); }
.b-mode-pill { display: inline-flex; align-items: center; gap: 7px; padding: 7px 12px; background: var(--b-pill-bg); border: 1px solid var(--b-pill-line);
  color: var(--b-pill-text); border-radius: 99px; font-size: .72rem; font-weight: 600; white-space: nowrap; }
.b-mode-dot { height: 6px; width: 6px; border-radius: 50%; background: var(--b-accent); }
/* ---------- Home hero ---------- */
.b-hero { position: relative; text-align: center; padding: 14px 18px 18px; overflow: hidden; isolation: isolate; }
.b-hero::before { content: ''; position: absolute; z-index: -1; width: 580px; height: 290px; border-radius: 50%;
  background: radial-gradient(ellipse, var(--b-glow) 0%, transparent 70%); top: -60px; left: 50%; transform: translateX(-50%); pointer-events: none; }
.b-orb { display: inline-grid; place-items: center; width: 67px; height: 67px; color: #fff; border-radius: 22px; transform: rotate(-8deg); margin: 2px 0 20px;
  background: radial-gradient(circle at 28% 18%, #d4c7fc 0, #ac93ec 23%, #8061da 64%, #6244b5 100%);
  box-shadow: inset 0 2px 5px rgba(255,255,255,.4), 0 13px 24px var(--b-shadow); }
.b-orb svg { transform: rotate(8deg); }
.stApp .b-hero h1 { font-size: clamp(2.3rem, 4.4vw, 3.65rem); line-height: 1.12; font-weight: 650; letter-spacing: -.04em; margin: 0 0 16px; padding: 0; }
.stApp .b-hero h1 span { color: var(--b-accent); }
.b-hero p { max-width: 470px; margin: 0 auto; color: var(--b-muted); font-size: .96rem; line-height: 1.75; }
.b-helper { text-align: center; color: var(--b-muted); font-size: .76rem; margin: 2px 0 16px; line-height: 1.6; }
.b-section-line { display: flex; justify-content: space-between; align-items: center; gap: 10px; margin: 17px 0 8px; }
.b-section-line h2 { font-size: .92rem; font-weight: 650; margin: 0; padding: 0; color: var(--b-text); }
.b-section-line span { color: var(--b-muted); font-size: .74rem; }
.st-key-beru_composer { max-width: 780px; margin: 0 auto; }
/* Quick-action cards */
[class*="st-key-beru_card_"] { background: var(--b-surface); border: 1px solid var(--b-line); border-radius: 18px; padding: 19px 17px 15px; height: 100%;
  box-shadow: 0 3px 10px var(--b-shadow); transition: transform .18s ease, border-color .18s ease; }
[class*="st-key-beru_card_"]:hover { transform: translateY(-3px); border-color: var(--b-accent); }
[class*="st-key-beru_card_"] [data-testid="stVerticalBlock"] { gap: .5rem; }
.b-icon { display: inline-flex; align-items: center; justify-content: center; width: 36px; height: 36px; border-radius: 11px; margin-bottom: 3px; color: var(--b-icon-fg); background: var(--b-icon-bg); }
.b-icon.mint { background: var(--b-mint-bg); color: var(--b-mint-fg); }
.b-icon.blue { background: var(--b-blue-bg); color: var(--b-blue-fg); }
.b-icon.peach { background: var(--b-peach-bg); color: var(--b-peach-fg); }
.b-card-copy { color: var(--b-muted); font-size: .78rem; line-height: 1.65; min-height: 48px; margin: 2px 0 0; }
[class*="st-key-beru_card_"] button { justify-content: flex-start !important; background: transparent !important; border: 0 !important; padding: 6px 0 !important;
  box-shadow: none !important; min-height: 38px !important; color: var(--b-text) !important; border-radius: 6px !important; }
[class*="st-key-beru_card_"] button > div, [class*="st-key-beru_card_"] button p { width: 100%; text-align: left; justify-content: flex-start; }
[class*="st-key-beru_card_"] button p { font-size: .9rem; font-weight: 650; line-height: 1.45; }
[class*="st-key-beru_card_"] button:hover { background: transparent !important; color: var(--b-accent) !important; border: 0 !important; }
.b-home-bottom { display: flex; justify-content: center; flex-wrap: wrap; gap: 9px; align-items: center; color: var(--b-muted); font-size: .74rem; padding: 22px 5px 8px; }
.b-home-bottom span { color: var(--b-line2); }
/* ---------- Inner pages ---------- */
.b-page-heading { padding: 8px 0 18px; }
.b-eyebrow { color: var(--b-accent); font-size: .7rem; text-transform: uppercase; letter-spacing: .13em; font-weight: 700; margin-bottom: 10px; }
.stApp .b-page-heading h1 { font-size: clamp(1.95rem, 3.5vw, 2.7rem); line-height: 1.17; letter-spacing: -.04em; margin: 0 0 12px; padding: 0; }
.b-page-heading p { max-width: 680px; color: var(--b-muted); font-size: .92rem; line-height: 1.75; margin: 0; }
[class*="st-key-beru_panel_"] { border: 1px solid var(--b-line); background: var(--b-surface); border-radius: 18px; padding: 23px; margin-bottom: 8px; }
.b-panel-title { font-size: 1rem; font-weight: 650; letter-spacing: -.01em; margin: 0 0 5px; color: var(--b-text); }
.b-panel-desc { color: var(--b-muted); font-size: .82rem; line-height: 1.7; margin: 0 0 14px; }
.b-empty { border: 1px dashed var(--b-line2); background: var(--b-empty); border-radius: 17px; padding: 42px 25px; text-align: center; margin: 15px 0; }
.stApp .b-empty h3 { font-size: 1.05rem; margin: 16px 0 9px; padding: 0; }
.b-empty p { font-size: .84rem; line-height: 1.7; color: var(--b-muted); max-width: 460px; margin: auto; }
.b-file { display: flex; justify-content: space-between; gap: 15px; align-items: center; border-bottom: 1px solid var(--b-line); padding: 12px 1px; font-size: .84rem; color: var(--b-text); }
.b-file-name { min-width: 0; overflow-wrap: anywhere; }
.b-file small { color: var(--b-muted); white-space: nowrap; font-size: .74rem; }
.b-note { background: var(--b-alert); color: var(--b-text); border: 1px solid var(--b-line); border-left: 4px solid var(--b-accent); padding: 12px 16px; border-radius: 11px; font-size: .82rem; line-height: 1.65; margin: 8px 0 17px; }
.b-monitor { margin: 11px 0 15px; }
.b-monitor-line { display: flex; justify-content: space-between; gap: 8px; font-size: .78rem; color: var(--b-muted); margin-bottom: 7px; }
.b-monitor-line strong { font-weight: 700; color: var(--b-text); }
.b-bar { height: 6px; border-radius: 99px; background: var(--b-track); overflow: hidden; }
.b-bar-fill { height: 100%; border-radius: 99px; background: var(--b-fill); }
.b-activity { border-left: 3px solid var(--b-accent); padding: 9px 12px; margin: 8px 0; font-size: .84rem; line-height: 1.7; color: var(--b-muted); overflow-wrap: anywhere; }
.b-activity strong { color: var(--b-accent); font-size: .76rem; }
/* ---------- Native widgets ---------- */
[data-testid="stWidgetLabel"], [data-testid="stWidgetLabel"] p, [data-testid="stWidgetLabel"] label { color: var(--b-text) !important; font-weight: 550; font-size: .84rem; }
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p { color: var(--b-muted) !important; opacity: 1 !important; line-height: 1.65; }
[data-testid="stTooltipIcon"] svg, [data-testid="stTooltipHoverTarget"] svg { color: var(--b-muted) !important; fill: var(--b-muted) !important; }
[data-testid="stText"], [data-testid="stText"] * { color: var(--b-text) !important; }
[data-baseweb="input"], [data-baseweb="base-input"], [data-baseweb="textarea"], [data-baseweb="select"] > div, [data-baseweb="select"] > div > div {background: var(--b-input) !important; color: var(--b-text) !important; border-radius: 10px !important; }
[data-baseweb="input"], [data-baseweb="textarea"], [data-baseweb="select"] > div { border: 1px solid var(--b-line2) !important; }
[data-baseweb="base-input"] { border: 0 !important; }
.stApp input, .stApp textarea { color: var(--b-text) !important; -webkit-text-fill-color: var(--b-text); caret-color: var(--b-accent); background: transparent !important; }
.stApp input::placeholder, .stApp textarea::placeholder { color: var(--b-placeholder) !important; -webkit-text-fill-color: var(--b-placeholder); opacity: 1 !important; }
[data-baseweb="input"]:focus-within, [data-baseweb="textarea"]:focus-within, [data-baseweb="select"]:focus-within > div { border-color: var(--b-accent) !important; box-shadow: 0 0 0 2px var(--b-tint) !important; }
[data-baseweb="select"] * { color: var(--b-text) !important; }
[data-baseweb="select"] svg { fill: var(--b-muted) !important; }

/* --- FIX: Selectbox Input Box (Aggressive Override) --- */
/* Targets every single div wrapper Streamlit uses */
[data-testid="stSelectbox"] div,
[data-testid="stSelectbox"] [data-baseweb="select"],
[data-testid="stSelectbox"] [data-baseweb="select"] > div,
[data-testid="stSelectbox"] [data-baseweb="select"] div[role="button"],
[data-testid="stSelectbox"] [data-baseweb="select"] div[role="combobox"] {
    background-color: var(--b-input) !important;
    background: var(--b-input) !important;
    border-color: var(--b-line2) !important;
    color: var(--b-text) !important;
}

/* Forces the text and SVGs inside to follow the theme */
[data-testid="stSelectbox"] span,
[data-testid="stSelectbox"] div,
[data-testid="stSelectbox"] p {
    color: var(--b-text) !important;
    -webkit-text-fill-color: var(--b-text) !important;
}

[data-testid="stSelectbox"] svg {
    fill: var(--b-muted) !important;
    color: var(--b-muted) !important;
}

/* Forces the actual border */
[data-testid="stSelectbox"] [data-baseweb="select"] {
    border: 1px solid var(--b-line2) !important;
    border-radius: 10px !important;
}

/* --- FIX: Dropdown Menu (Portal) --- */
/* Streamlit renders the dropdown menu in a portal outside the main app. 
   We must force Streamlit's internal BaseWeb variables here. */
[data-baseweb="popover"], 
[data-baseweb="popover"] > div, 
[data-baseweb="menu"], 
[data-baseweb="popover"] ul, 
ul[role="listbox"] {
    background-color: var(--b-popover) !important; 
    color: var(--b-text) !important; 
    
    /* Override Streamlit's hidden internal theme variables */
    --background-color: var(--b-popover) !important;
    --color: var(--b-text) !important;
    --primary: var(--b-accent) !important;
    --primary50: var(--b-tint) !important;
    --secondary: var(--b-hover) !important;
    --secondary50: var(--b-hover) !important;
}

/* Force the list items to ignore React's dark mode defaults */
[data-baseweb="popover"] li[role="option"] {
    background-color: transparent !important;
    color: var(--b-text) !important;
    -webkit-text-fill-color: var(--b-text) !important;
}

[data-baseweb="popover"] li[role="option"] * {
    color: var(--b-text) !important;
    -webkit-text-fill-color: var(--b-text) !important;
    background-color: transparent !important;
}

/* Hover and Selected states */
[data-baseweb="popover"] li[role="option"]:hover, 
[data-baseweb="popover"] li[role="option"][aria-selected="true"] {
    background-color: var(--b-hover) !important;
}

/* Fix the text color inside the selected/hovered items */
[data-baseweb="popover"] li[role="option"]:hover *,
[data-baseweb="popover"] li[role="option"][aria-selected="true"] * {
    color: var(--b-text) !important;
    -webkit-text-fill-color: var(--b-text) !important;
}

[data-baseweb="popover"] :is(li, span, p, label, div) { 
    color: var(--b-text) !important; 
    background-color: transparent !important;
    
    /* Override hidden text variables */
    --color: var(--b-text) !important;
}

[data-baseweb="popover"] li:hover, 
li[role="option"]:hover, 
li[role="option"][aria-selected="true"] { 
    background-color: var(--b-hover) !important; 
    color: var(--b-text) !important;
    
    --background-color: var(--b-hover) !important;
    --color: var(--b-text) !important;
}

/* Sometimes BaseWeb uses nested divs for the actual text */
[data-baseweb="popover"] li > div,
[data-baseweb="popover"] li > div > div {
    background-color: transparent !important;
    color: var(--b-text) !important;
    -webkit-text-fill-color: var(--b-text) !important;
}
[data-testid="stTooltipContent"] { background: var(--b-popover) !important; color: var(--b-text) !important; }
/* Buttons */
[data-testid="stButton"] button, [data-testid="stDownloadButton"] button { background: var(--b-surface) !important; color: var(--b-text) !important;
  border: 1px solid var(--b-line2) !important; border-radius: 11px; font-weight: 550; min-height: 42px; padding: 9px 16px; transition: background .15s ease, border-color .15s ease; }
[data-testid="stButton"] button p, [data-testid="stDownloadButton"] button p { color: inherit !important; }
[data-testid="stButton"] button:hover, [data-testid="stDownloadButton"] button:hover { background: var(--b-tint) !important; border-color: var(--b-accent) !important; color: var(--b-tint-text) !important; }
/* Keep navigation quiet and quick actions visually integrated with their cards.
   These rules follow the global button styles so the global outline cannot win. */
.stApp .st-key-beru_navigation [data-testid="stButton"] button:not([kind="primary"]):not([data-testid="stBaseButton-primary"]) {
  background: transparent !important; color: var(--b-muted) !important;
  border: 1px solid transparent !important; box-shadow: none !important;
}
.stApp .st-key-beru_navigation [data-testid="stButton"] button:not([kind="primary"]):not([data-testid="stBaseButton-primary"]):hover {
  background: var(--b-hover) !important; color: var(--b-text) !important;
  border-color: transparent !important;
}
.stApp [class*="st-key-beru_card_"] [data-testid="stButton"] button {
  justify-content: flex-start !important; text-align: left !important;
  background: transparent !important; color: var(--b-text) !important;
  border: 0 !important; border-radius: 7px !important; box-shadow: none !important;
  min-height: 38px !important; padding: 6px 0 !important;
}
.stApp [class*="st-key-beru_card_"] [data-testid="stButton"] button > div,
.stApp [class*="st-key-beru_card_"] [data-testid="stButton"] button p {
  width: 100%; text-align: left; justify-content: flex-start;
}
.stApp [class*="st-key-beru_card_"] [data-testid="stButton"] button p {
  font-size: .9rem; font-weight: 650; line-height: 1.45;
}
.stApp [class*="st-key-beru_card_"] [data-testid="stButton"] button:hover {
  background: transparent !important; color: var(--b-accent) !important; border: 0 !important;
}
.stApp [data-testid="stWidgetLabel"] { user-select: none; }
[data-testid="stButton"] button:is([kind="primary"], [data-testid="stBaseButton-primary"]) { background: var(--b-btn) !important; border-color: var(--b-btn) !important; color: var(--b-on-btn) !important; }
[data-testid="stButton"] button:is([kind="primary"], [data-testid="stBaseButton-primary"]):hover { background: var(--b-btn2) !important; border-color: var(--b-btn2) !important; color: var(--b-on-btn) !important; }
[data-testid="stButton"] button:disabled { opacity: .5; cursor: not-allowed; }
button:focus-visible, a:focus-visible, summary:focus-visible, textarea:focus-visible { outline: 3px solid var(--b-focus) !important; outline-offset: 2px; }
/* Chat input */
[data-testid="stBottom"], [data-testid="stBottom"] > div, [data-testid="stBottomBlockContainer"] { background: var(--b-bg) !important; }
[data-testid="stChatInput"] { background: var(--b-input) !important; border: 1px solid var(--b-line2) !important; border-radius: 18px !important; box-shadow: 0 6px 24px var(--b-shadow); min-height: 70px; }
[data-testid="stChatInput"] :is(div, [data-baseweb]) { background: transparent !important; border: 0 !important; box-shadow: none !important; }
[data-testid="stChatInput"]:focus-within { border-color: var(--b-accent) !important; box-shadow: 0 0 0 3px var(--b-tint) !important; }
[data-testid="stChatInput"] textarea { color: var(--b-text) !important; -webkit-text-fill-color: var(--b-text); font-size: .96rem; padding: 18px 16px; }
[data-testid="stChatInput"] textarea:disabled { opacity: .6; }
[data-testid="stChatInputSubmitButton"] { background: var(--b-btn) !important; color: var(--b-on-btn) !important; border-radius: 11px !important; }
[data-testid="stChatInputSubmitButton"] svg { color: inherit !important; fill: currentColor !important; }
[data-testid="stChatInputSubmitButton"]:disabled { background: var(--b-tint) !important; color: var(--b-tint-text) !important; opacity: .7; }
/* Chat bubbles */
[data-testid="stChatMessage"] { background: var(--b-surface) !important; border: 1px solid var(--b-line); border-radius: 17px; padding: 18px 20px; margin-bottom: 10px; color: var(--b-text) !important; }
[data-testid="stChatMessage"]:has(:is([data-testid="stChatMessageAvatarUser"], [data-testid="chatAvatarIcon-user"])) { background: var(--b-user-bg) !important; border-color: var(--b-user-line); }
[data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] :is(p, li, h1, h2, h3, h4, h5, h6, strong, em, span, td, th, blockquote):not(pre *) { color: var(--b-text) !important; line-height: 1.75; }
[data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] a { color: var(--b-accent) !important; }
[data-testid="stChatMessageAvatarUser"], [data-testid="chatAvatarIcon-user"] { background: var(--b-av-user-bg) !important; color: var(--b-av-user-fg) !important; }
[data-testid="stChatMessageAvatarAssistant"], [data-testid="chatAvatarIcon-assistant"] { background: var(--b-av-ai-bg) !important; color: var(--b-av-ai-fg) !important; }
[data-testid="stChatMessage"] :is([data-testid="stChatMessageAvatarUser"], [data-testid="stChatMessageAvatarAssistant"]) svg { color: inherit !important; fill: currentColor !important; }
/* Expanders (the dark header bug lived here) */
[data-testid="stExpander"] { background: var(--b-surface) !important; border: 1px solid var(--b-line) !important; border-radius: 12px !important; overflow: hidden; }
[data-testid="stChatMessage"] [data-testid="stExpander"] { background: var(--b-surface2) !important; }
[data-testid="stExpander"] details, [data-testid="stExpander"] summary { background: transparent !important; color: var(--b-text) !important; border: 0 !important; }
[data-testid="stExpander"] summary { padding: 11px 13px; }
[data-testid="stExpander"] summary:hover { background: var(--b-hover) !important; }
[data-testid="stExpander"] summary :is(p, span, div) { color: var(--b-text) !important; }
[data-testid="stExpander"] summary p { font-size: .84rem; font-weight: 600; }
[data-testid="stExpander"] summary svg { color: var(--b-muted) !important; fill: var(--b-muted) !important; }
/* Alerts */
[data-testid="stAlert"], [data-testid="stAlertContainer"] { background: var(--b-alert) !important; color: var(--b-text) !important; border-radius: 12px; }
[data-testid="stAlertContainer"], [data-testid="stAlert"]:not(:has([data-testid="stAlertContainer"])) { border: 1px solid var(--b-line); border-left: 4px solid var(--b-accent); }
[data-testid="stAlert"] :is(p, span, div, li, a, strong) { color: var(--b-text) !important; }
[data-testid="stSpinner"], [data-testid="stSpinner"] * { color: var(--b-muted) !important; }
/* Code: always a dark surface with light text so it is readable in both themes */
[data-testid="stCode"], [data-testid="stCode"] pre, pre { background: var(--b-code-bg) !important; color: var(--b-code-text) !important; border-radius: 11px; }
[data-testid="stCode"] code, pre code, pre span, [data-testid="stCode"] span { color: var(--b-code-text) !important; background: transparent !important; }
[data-testid="stCode"] button { background: transparent !important; color: var(--b-code-text) !important; border: 0 !important; }
:not(pre) > code { background: var(--b-icode-bg) !important; color: var(--b-icode-text) !important; border-radius: 6px; padding: .12em .4em; }
code, pre, pre span { font-family: ui-monospace, "SFMono-Regular", Consolas, monospace !important; }
hr { border-color: var(--b-line); }
/* ---------- Responsive ---------- */
@media (max-width: 1200px) {
  [data-testid="stMainBlockContainer"], .main .block-container { padding: 3rem 2rem 4rem; }
  [class*="st-key-beru_card_"] { padding: 17px 13px 12px; }
}
@media (max-width: 850px) {
  .stApp .b-hero h1 { font-size: 2.65rem; }
  .b-card-copy { min-height: 0; }
  [data-testid="stMain"] [data-testid="stHorizontalBlock"] { flex-wrap: wrap; }
  [data-testid="stMain"] [data-testid="stColumn"] { min-width: min(100%, 240px) !important; flex: 1 1 240px !important; }
}
@media (max-width: 600px) {
  [data-testid="stMainBlockContainer"], .main .block-container { padding: 3.8rem 1rem 3rem; }
  .b-topbar { gap: 8px; padding-bottom: 15px; align-items: flex-start; }
  .b-breadcrumb { font-size: .74rem; gap: 6px; flex-wrap: wrap; }
  .b-mode-pill { font-size: .64rem; padding: 6px 9px; max-width: 150px; white-space: normal; }
  .stApp .b-hero h1 { font-size: 2.3rem; }
  .b-hero p { font-size: .88rem; }
  .b-orb { width: 56px; height: 56px; border-radius: 18px; margin-bottom: 19px; }
  .b-section-line span { display: none; }
  [class*="st-key-beru_panel_"] { padding: 17px; }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { transition: none !important; animation: none !important; scroll-behavior: auto !important; }
}
"""

# Narrower reading column while a conversation is on screen.
CONVERSATION_CSS = '[data-testid="stMainBlockContainer"], .main .block-container { max-width: 980px; }'


def build_css(theme: str) -> str:
    palette = DARK if theme == "Dark" else LIGHT
    variables = "\n".join(f"  --b-{name}: {value};" for name, value in palette.items())
    
    # 1. Apply variables to the root
    root = f":root {{\n  color-scheme: {'dark' if theme == 'Dark' else 'light'};\n{variables}\n}}"
    
    # 2. BRUTE FORCE FIX: Streamlit's dropdown menu (popover) renders outside the app 
    # container (in a React Portal). We must inject these CSS variables onto the body 
    # tag so the portal inherits the correct background and text colors.
    portal_fix = f"""
    html, body, [data-baseweb="popover"], [data-baseweb="menu"], ul[role="listbox"] {{
        --primary: {palette['accent']} !important;
        --background-color: {palette['popover']} !important;
        --color: {palette['text']} !important;
        background-color: {palette['popover']} !important;
        color: {palette['text']} !important;
    }}
    """
    
    css = f"{root}\n{portal_fix}\n{BASE_CSS}"
    # A blank line would end the Markdown HTML block and print CSS as text.
    css = "\n".join(line for line in css.splitlines() if line.strip())
    return f"<style>\n{css}\n</style>"


def system_theme() -> str:
    """First-visit default: follow the browser/Streamlit theme when it is known."""
    try:
        return "Dark" if st.context.theme.type == "dark" else "Light"
    except Exception:
        return "Light"


# Small inline vectors are decorative; button labels carry the meaning.
ICON_PATHS = {
    "spark": '<path d="M12 2l2.8 7.2L22 12l-7.2 2.8L12 22l-2.8-7.2L2 12l7.2-2.8L12 2z"/>',
    "computer": '<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8M12 17v4M7 11h3l2-4 2 7 2-3h2"/>',
    "code": '<path d="M8 6l-6 6 6 6M16 6l6 6-6 6M14 3l-4 18"/>',
    "website": '<path d="M12 3l8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3zM8 12l3 3 5-6"/>',
    "market": '<path d="M4 4v16h16M7 14l4-4 4 2 5-7M16 5h4v4"/>',
    "tools": '<path d="M15 5l4 4M3 21l6-6M14 3a5 5 0 0 0-5 7L3 16a3 3 0 0 0 5 5l6-6a5 5 0 0 0 7-5l-4 3-4-4 3-5z"/>',
    "history": '<path d="M3 10a9 9 0 1 1 1 7M3 4v6h6M12 7v5l3 2"/>',
    "file": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M8 13h8M8 17h5"/>',
}


def icon(name: str, size: int = 21) -> str:
    """Return trusted, static SVG markup; never insert user markup here."""
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" '
            'fill="none" stroke="currentColor" stroke-width="1.6" '
            'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
            f'{ICON_PATHS.get(name, ICON_PATHS["spark"])}</svg>')


def h(value: Any) -> str:
    return escape(str(value), quote=True)


def html(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


def wide(fn: Callable) -> dict[str, Any]:
    """Full-width kwargs that work on both older and newer Streamlit versions."""
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return {}
    if "width" in params:
        return {"width": "stretch"}
    if "use_container_width" in params:
        return {"use_container_width": True}
    return {}


def panel(key: str):
    """Use keyed styling where supported; older installs retain usable controls."""
    if "key" in inspect.signature(st.container).parameters:
        return st.container(key=key)
    return st.container()


def field(widget: Callable, label: str, *, key: str, default: Any, **kwargs):
    """Preserve input values when a page is hidden by the sidebar navigation.

    Separate saved keys survive Streamlit's cleanup of unrendered widgets.
    Options are checked before rendering, so changing India/US cannot keep an
    incompatible exchange. No backend parameters are transformed here.
    """
    saved_key = "beru_saved_" + key
    if key not in st.session_state:
        st.session_state[key] = st.session_state.get(saved_key, default)
    options = kwargs.get("options")
    if options is not None and st.session_state[key] not in options:
        st.session_state[key] = default
    result = widget(label, key=key, **kwargs)
    st.session_state[saved_key] = result
    return result


def heading(eyebrow: str, title: str, description: str) -> None:
    html(f'<div class="b-page-heading"><div class="b-eyebrow">{h(eyebrow)}</div>'
         f'<h1>{h(title)}</h1><p>{h(description)}</p></div>')


def empty_state(name: str, title: str, description: str) -> None:
    html(f'<div class="b-empty"><div class="b-icon">{icon(name)}</div>'
         f'<h3>{h(title)}</h3><p>{h(description)}</p></div>')


def error_details(message: str, exc: Exception) -> None:
    st.error(message)
    with st.expander("Technical details"):
        st.code(f"{type(exc).__name__}: {exc}", language="text")


def show_json(data: Any) -> None:
    """JSON as a code block: always readable, whatever the Streamlit theme."""
    try:
        text = json.dumps(data, indent=2, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(data)
    st.code(text, language="json")


def init_state() -> None:
    defaults = {
        "messages": [], "mode": "General", "quick_prompt": "",
        "beru_page": "Assistant", "beru_prompt_labels": {},
        "beru_activity": {}, "beru_quick_label": "", "beru_pending": False,
        "beru_theme_mode": system_theme(),
        "beru_session_id": uuid.uuid4().hex,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    if st.session_state.mode not in MODE_LABELS:
        st.session_state.mode = "General"
    if st.session_state.beru_page not in PAGES:
        st.session_state.beru_page = "Assistant"
    if st.session_state.beru_theme_mode not in ("Light", "Dark"):
        st.session_state.beru_theme_mode = "Light"


def reset_conversation() -> None:
    # Same scope as the original PURGE_SESSION_LOG: never delete files/traces.
    st.session_state.messages = []
    st.session_state.quick_prompt = ""
    st.session_state.beru_quick_label = ""
    st.session_state.beru_prompt_labels = {}
    st.session_state.beru_activity = {}
    st.session_state.beru_pending = False
    st.session_state.beru_session_id = uuid.uuid4().hex
    st.session_state.beru_page = "Assistant"
    st.session_state.pop("beru_agent_error", None)


def set_theme(value: str) -> None:
    st.session_state.beru_theme_mode = value


def go_to(name: str) -> None:
    st.session_state.beru_page = name


def retry_last_request() -> None:
    """Manual retry only: tools can have side effects, so nothing re-runs by itself."""
    st.session_state.pop("beru_agent_error", None)
    st.session_state.beru_pending = True


def get_hardware_telemetry() -> dict[str, Any]:
    """Keep the same sensors. Retain C: on Windows; avoid a crash elsewhere.

    These are snapshots on rerun, not a continuous background health monitor.
    A restricted/unavailable sensor is shown as unavailable, never as healthy.
    """
    def read(fn: Callable, default=None):
        try:
            return fn()
        except (OSError, psutil.Error, RuntimeError):
            return default

    cpu = read(lambda: psutil.cpu_percent(interval=0.1))
    cpu_cores = read(lambda: psutil.cpu_count(logical=True))
    ram = read(psutil.virtual_memory)
    disk_root = "C:\\" if os.name == "nt" else (Path.cwd().anchor or "/")
    disk = read(lambda: psutil.disk_usage(disk_root))
    net = read(psutil.net_io_counters)
    return {
        "cpu": cpu, "cpu_cores": cpu_cores, "ram": ram, "disk": disk,
        "disk_root": disk_root,
        "net_tx_mb": net.bytes_sent / (1024 * 1024) if net else None,
        "net_rx_mb": net.bytes_recv / (1024 * 1024) if net else None,
        "pids": read(lambda: len(psutil.pids())),
        "uptime": read(lambda: int((time.time() - psutil.boot_time()) // 3600)),
    }


def percent_bar(label: str, value: Any) -> None:
    if value is None:
        st.caption(f"{label}: unavailable")
        return
    width = min(100.0, max(0.0, float(value)))
    html(f'<div class="b-monitor"><div class="b-monitor-line"><span>{h(label)}</span>'
         f'<strong>{width:.0f}%</strong></div><div class="b-bar">'
         f'<div class="b-bar-fill" style="width:{width:.1f}%"></div></div></div>')


def list_directory(path: Any, pattern: str = "*") -> list[Path]:
    try:
        return sorted(Path(path).glob(pattern), key=lambda p: p.name.lower())
    except (OSError, TypeError, ValueError):
        return []


def sidebar() -> str:
    with st.sidebar:
        html(f'<div class="b-brand"><div class="b-brandmark">{icon("spark", 25)}</div>'
             '<div><div class="b-brandname">beru<span class="b-dot">.</span></div>'
             '<div class="b-brandline">Your everyday AI workspace</div></div></div>')

        html('<div class="b-theme-label">APPEARANCE</div>')
        theme = st.session_state.beru_theme_mode
        with panel("beru_themeswitch"):
            light_col, dark_col = st.columns(2)
            with light_col:
                st.button("☀ Light", key="beru_theme_light", **wide(st.button),
                          type="primary" if theme == "Light" else "secondary",
                          on_click=set_theme, args=("Light",),
                          help="Use the light appearance. Your conversation is not affected.")
            with dark_col:
                st.button("☾ Dark", key="beru_theme_dark", **wide(st.button),
                          type="primary" if theme == "Dark" else "secondary",
                          on_click=set_theme, args=("Dark",),
                          help="Use the dark appearance. Your conversation is not affected.")

        st.button("＋  New conversation", **wide(st.button), type="primary",
                  key="beru_new_chat", on_click=reset_conversation,
                  help="Clear this chat. Saved files and activity logs are not deleted.")

        html('<div class="b-nav-label">YOUR WORKSPACE</div>')
        current = st.session_state.beru_page
        with panel("beru_navigation"):
            for position, name in enumerate(PAGES):
                st.button(NAV_LABELS[name], key=f"beru_navbtn_{position}", **wide(st.button),
                          type="primary" if name == current else "secondary",
                          on_click=go_to, args=(name,))

        html('<div class="b-sidebar-divider"></div>')
        chosen_mode = field(
            st.selectbox, "Help me with", key="beru_mode", default=st.session_state.mode,
            options=list(MODE_LABELS), format_func=lambda value: MODE_LABELS[value],
            help="Medical, Reverse Engineering, Data Analyst and API modes use a localhost model and restricted tools. Medical results are not professional advice.",
        )
        st.session_state.mode = chosen_mode
        st.caption(MODE_HINTS[chosen_mode])

        key_ui.render_sidebar_keys()  # <--- ADD THIS LINE

        with st.expander("Computer & app details", expanded=False):
            telemetry = get_hardware_telemetry()
            st.caption("A snapshot of the computer running BERU. Refreshes when the app reruns.")
            percent_bar("Processor in use", telemetry["cpu"])
            percent_bar("Memory in use", telemetry["ram"].percent if telemetry["ram"] else None)
            percent_bar("Storage used", telemetry["disk"].percent if telemetry["disk"] else None)
            if telemetry["ram"]:
                ram = telemetry["ram"]
                st.caption(f"Memory: {ram.used / (1024**3):.1f} / {ram.total / (1024**3):.1f} GB")
            if telemetry["disk"]:
                st.caption(f"Storage ({telemetry['disk_root']}): {telemetry['disk'].free / (1024**3):.1f} GB free")
            if telemetry["cpu_cores"] is not None:
                st.caption(f"Processor threads: {telemetry['cpu_cores']}")
            for label, key, suffix in (("Data sent", "net_tx_mb", " MB"),
                                       ("Data received", "net_rx_mb", " MB"),
                                       ("Running processes", "pids", ""),
                                       ("Time since restart", "uptime", " hours")):
                value = telemetry[key]
                if value is not None:
                    value = f"{value:.1f}" if isinstance(value, float) else str(value)
                    st.caption(f"{label}: {value}{suffix}")
            st.markdown("**Configured AI models**")
            st.caption(f"Primary: {PRIMARY_MODEL}\n\nFallback: {GEMINI_MODEL}")
            st.caption("These are configuration values, not a connection or health test.")
            try:
                st.caption(f"Registered tools: {len(get_live_tools())} · Custom tools: {len(ACTIVE_FORGED_TOOLS)}")
            except Exception as exc:
                st.caption(f"Tool count unavailable ({type(exc).__name__}).")
            st.caption(f"Workspace items: {len(list_directory(WORKSPACE_DIR))} · "
                       f"Saved activity files: {len(list_directory(TRACES_DIR, '*.jsonl'))}")
            st.caption(f"Workspace: {WORKSPACE_DIR}\n\nActivity files: {TRACES_DIR}")

        html('<div class="b-tip"><div class="b-small-spark">✧</div>'
             '<div class="b-tip-title">Start with your own words.</div>'
             '<p>You don’t need to know the right command. Just describe what you’d like to do.</p></div>')
        html('<div class="b-sidebar-footer">A little help. A lot more possible.</div>')
    return st.session_state.beru_page


def topbar(page: str) -> None:
    html('<div class="b-topbar"><div class="b-breadcrumb">'
         f'<span>Your workspace</span><span class="b-slash">/</span><strong>{h(page)}</strong></div>'
         f'<div class="b-mode-pill"><span class="b-mode-dot"></span>{h(MODE_LABELS[st.session_state.mode])}</div></div>')


def quick_actions(disabled: bool = False) -> None:
    actions = [
        ("computer", "Check my computer", "Understand processor, memory, storage and running apps.", "mint"),
        ("code", "Review my code", "Check modes/developer.py for potential security issues.", ""),
        ("website", "Check a website", "Run the existing demo checks on scanme.nmap.org.", "blue"),
        ("market", "Explore a stock", "Start with a company name. Explore data, not trading advice.", "peach"),
    ]
    for col, (key, title, copy, tint) in zip(st.columns(4), actions):
        with col, panel("beru_card_" + key):
            html(f'<div class="b-icon {tint}">{icon(key)}</div>')
            if st.button(title + "  ↗", key="beru_quick_" + key, disabled=disabled, **wide(st.button),
                         help="Runs this task immediately using the current assistant mode."):
                st.session_state.quick_prompt = QUICK_PROMPTS[key]
                st.session_state.beru_quick_label = title
            html(f'<div class="b-card-copy">{h(copy)}</div>')


def render_activity(activity: dict[str, Any]) -> None:
    for thought in activity.get("thoughts", []):
        st.write(thought)
    for call in activity.get("tools", []):
        st.markdown(f"**Tool:** `{call['name']}`")
        if isinstance(call["args"], (dict, list)):
            show_json(call["args"])
        else:
            st.code(str(call["args"]), language="text")


def render_message(index: int, msg: dict[str, Any]) -> None:
    with st.chat_message(msg["role"]):
        label = st.session_state.beru_prompt_labels.get(index)
        if label:
            st.markdown(label)
            with st.expander("Full request sent to BERU"):
                st.markdown(msg["content"])
        else:
            st.markdown(msg["content"])
        activity = st.session_state.beru_activity.get(index)
        if activity and (activity["thoughts"] or activity["tools"]):
            with st.expander("What BERU did", expanded=False):
                render_activity(activity)
        if msg["role"] == "assistant":
            render_answer_feedback(index, msg, activity or {})


def render_answer_feedback(index: int, msg: dict[str, Any], activity: dict[str, Any]) -> None:
    """Collect optional local feedback without storing prompt or answer text."""
    session_id = st.session_state.beru_session_id
    try:
        already_submitted = has_answer_feedback(session_id, index)
    except Exception:
        already_submitted = False
    if already_submitted:
        st.caption("Thanks for helping improve BERU.")
        return

    mode = activity.get("mode", st.session_state.mode)
    private_modes = {"medical", "reverse engineering", "data analyst", "api", "watchdog"}
    with st.expander("Give feedback", expanded=False):
        st.caption("Feedback is stored locally as a rating, issue category, and answer hash. The conversation text is not saved by this form.")
        with st.form(key=f"beru_feedback_{session_id}_{index}"):
            rating_label = st.radio(
                "Was this answer useful?", ("Helpful", "Needs improvement"),
                horizontal=True, key=f"beru_feedback_rating_{session_id}_{index}",
            )
            reason_label = st.selectbox(
                "What should improve?",
                ("No specific issue", "Accuracy", "Completeness", "Format", "Tool choice", "Speed", "Other"),
                key=f"beru_feedback_reason_{session_id}_{index}",
            )
            style_label = "Keep current preference"
            style_map = {
                "Keep current preference": "keep",
                "Concise answers": "concise",
                "Detailed explanations": "detailed",
                "Use bullet points": "bullets",
                "Explain technical terms simply": "plain_language",
                "Clear saved style preference": "clear",
            }
            if mode.casefold() not in private_modes:
                style_label = st.selectbox(
                    "Optional default style for future chats",
                    tuple(style_map),
                    key=f"beru_feedback_style_{session_id}_{index}",
                )
            submitted = st.form_submit_button("Send feedback", **wide(st.form_submit_button))
        if submitted:
            ratings = {"Helpful": "helpful", "Needs improvement": "not_helpful"}
            reasons = {
                "No specific issue": "none", "Accuracy": "accuracy",
                "Completeness": "incomplete", "Format": "format",
                "Tool choice": "tool_selection", "Speed": "slow", "Other": "other",
            }
            try:
                record_answer_feedback(
                    session_id, index, mode, ratings[rating_label], reasons[reason_label],
                    str(msg.get("content", "")),
                )
            except Exception as exc:
                error_details("Feedback couldn’t be saved.", exc)
                return
            preference_error = None
            if mode.casefold() not in private_modes:
                selected_style = style_map[style_label]
                try:
                    if selected_style == "clear":
                        set_response_style_preference(None)
                    elif selected_style != "keep":
                        set_response_style_preference(selected_style)
                except Exception as exc:
                    preference_error = exc
            if preference_error:
                st.warning("Feedback was saved, but the response-style preference couldn’t be updated.")
                st.caption(f"Preference error: {type(preference_error).__name__}")
            else:
                st.success("Feedback saved locally. Thanks for helping improve BERU.")


def run_pending_request() -> None:
    """Run the agent for the last user message, then rerun to show the result.

    The pending flag is cleared FIRST. If the run is interrupted, nothing is
    re-sent automatically; the person sees a "Try again" button instead.
    """
    state = st.session_state
    state.beru_pending = False
    prompt = state.messages[-1]["content"]
    history = state.messages[:-1]
    thoughts_list: list[Any] = []
    tools_list: list[dict[str, Any]] = []

    with st.chat_message("assistant"):
        with st.expander("What BERU is doing", expanded=True):
            thought_box = st.empty()
            tools_box = st.empty()

        def on_th(t):
            thoughts_list.append(t)
            try:
                thought_box.markdown(
                    '<div class="b-activity"><strong>Progress</strong><br>'
                    + '<br>'.join(h(value) for value in thoughts_list[-2:]) + '</div>',
                    unsafe_allow_html=True)
            except Exception:
                pass  # a background thread may not be able to draw; never break the agent

        def on_call(name, args):
            tools_list.append({"name": name, "args": args})
            try:
                tools_box.markdown(
                    '<div class="b-activity"><strong>Tools being used</strong><br>'
                    + '<br>'.join(f'{h(call["name"])} · {h(call["args"])}' for call in tools_list[-3:])
                    + '</div>', unsafe_allow_html=True)
            except Exception:
                pass

        failure = None
        response: Any = None
        try:
            with st.spinner("BERU is working on it…"):
                response = run_agent(
                    prompt,
                    mode=state.mode,
                    history=history,
                    on_thought=on_th,
                    on_tool_call=on_call,
                )
        except Exception as exc:
            failure = f"{type(exc).__name__}: {exc}"

    if failure is not None:
        state.beru_agent_error = failure
        st.rerun()
    assistant_index = len(state.messages)
    state.messages.append({"role": "assistant", "content": response if isinstance(response, str) else str(response)})
    state.beru_activity[assistant_index] = {
        "thoughts": thoughts_list, "tools": tools_list, "mode": state.mode,
    }
    st.rerun()


def render_assistant() -> None:
    state = st.session_state
    busy = bool(state.beru_pending)
    messages = state.messages
    user_input = None

    if not messages:
        html(f'<section class="b-hero"><div class="b-orb">{icon("spark", 34)}</div>'
             '<h1>A little help.<br><span>A lot more possible.</span></h1>'
             '<p>Ask a question, make something, or let BERU help with the busywork.</p></section>')
        with panel("beru_composer"):
            user_input = st.chat_input("What would you like a hand with?", key="beru_chat_input", disabled=busy)
        html('<div class="b-helper">Use your own words. Press Enter to send.</div>')
        html('<div class="b-section-line"><h2>A few things to try</h2><span>Choose a task to get started</span></div>')
        quick_actions(busy)
        html('<div class="b-home-bottom">Everyday tasks<span>·</span>Creative ideas<span>·</span>'
             'Code & research<span>·</span>Your next big thing</div>')
    else:
        html("<style>" + CONVERSATION_CSS + "</style>")
        # Called at page level, so Streamlit pins it to the bottom of the window.
        user_input = st.chat_input("Ask a follow-up, or start something new…", key="beru_chat_input", disabled=busy)
        for index, msg in enumerate(messages):
            render_message(index, msg)
        if busy:
            run_pending_request()  # ends with st.rerun()
        else:
            if messages[-1]["role"] == "user":
                failure = state.get("beru_agent_error")
                if failure:
                    st.error("BERU couldn’t finish that request. Nothing was retried automatically.")
                    with st.expander("Technical details from the last request"):
                        st.code(failure, language="text")
                else:
                    st.warning("This request didn’t finish. It may have been interrupted.")
                st.button("Try this request again", key="beru_retry", on_click=retry_last_request,
                          help="Sends the same request to BERU once more.")
            with st.expander("Quick tasks", expanded=False):
                quick_actions(False)

    # Same dispatch priority as the original: typed text first, then a quick action.
    target_prompt = state.quick_prompt
    quick_label = state.beru_quick_label
    state.quick_prompt = ""
    state.beru_quick_label = ""
    final_prompt = user_input or target_prompt
    if not final_prompt or busy:
        return

    user_index = len(state.messages)
    state.messages.append({"role": "user", "content": final_prompt})
    if not user_input and quick_label:
        state.beru_prompt_labels[user_index] = quick_label
    state.pop("beru_agent_error", None)
    state.beru_pending = True
    st.rerun()  # redraw as a conversation, then run the agent


def render_market() -> None:
    heading("Stock explorer", "A little more clarity. A bigger picture.",
            "Explore stock price charts for India and the US. Choose a listing and a time interval; BERU uses your configured data source or local CSV files.")
    html('<div class="b-note">For research only. This workspace does not place orders or provide personalized buy/sell instructions.</div>')
    with panel("beru_panel_market"):
        market_col, exchange_col, symbol_col, interval_col = st.columns([1, 1, 1.4, 1.15])
        with market_col:
            chart_market = field(st.selectbox, "Market", options=["India", "US"],
                                 key="market_lab_market", default="India")
        with exchange_col:
            exchanges = ["NSE", "BSE"] if chart_market == "India" else ["NASDAQ", "NYSE", "AMEX"]
            chart_exchange = field(st.selectbox, "Stock exchange", options=exchanges,
                                   key="market_lab_exchange", default=exchanges[0])
        with symbol_col:
            chart_symbol = field(st.text_input, "Stock symbol", placeholder="e.g. RELIANCE or MSFT",
                                 key="market_lab_symbol", default="",
                                 help="The short listing code used by the exchange. Not sure? Ask the Assistant using the company name.")
        with interval_col:
            chart_interval = field(st.selectbox, "Show each price candle", options=list(INTERVAL_LABELS),
                                   format_func=lambda value: INTERVAL_LABELS[value],
                                   key="market_lab_interval", default="1d")
        chart_horizon = "intraday" if chart_interval in {"5m", "15m", "1h"} else ("long_term" if chart_interval == "1wk" else "swing")
        if st.button("Explore this stock  ↗", type="primary", key="market_lab_load"):
            if not chart_symbol.strip():
                st.warning("Enter a stock symbol first, such as RELIANCE or MSFT.")
            else:
                st.session_state.pop("beru_market_result", None)
                try:
                    import plotly.graph_objects  # noqa: F401  (fail early with a clear message)
                except ImportError:
                    st.error("Charts need Plotly. Install your project requirements with: pip install -r requirements.txt")
                else:
                    try:
                        with st.spinner("Loading the chart from your data source…"):
                            normalized = market_core._normalize_inputs(chart_market, chart_exchange, chart_symbol, chart_interval, chart_horizon)
                            candles, source = market_core._provider.load_candles(*normalized[:4])
                            if not candles:
                                st.warning("Your data source returned no price candles for this selection.")
                            else:
                                # Store real results, not synthetic prices. Analysis uses the exact original call.
                                result = {
                                    "normalized": normalized, "candles": candles, "source": source,
                                    "selection": (chart_market, chart_exchange, chart_symbol, chart_interval),
                                    "analysis": None, "analysis_error": None,
                                }
                                try:
                                    result["analysis"] = market_core.analyze_stock_market(
                                        normalized[2], chart_market, chart_exchange, chart_horizon, chart_interval)
                                except Exception as exc:
                                    result["analysis_error"] = f"{type(exc).__name__}: {exc}"
                                st.session_state.beru_market_result = result
                    except market_core.MarketDataError as exc:
                        error_details("Market data isn’t available for this selection.", exc)
                    except Exception as exc:
                        error_details("The chart couldn’t be loaded. Check the symbol and data-source settings.", exc)

    result = st.session_state.get("beru_market_result")
    if not result:
        empty_state("market", "Your next insight starts here.",
                    "Pick a stock above to see its chart. Available history and intervals depend on your data provider; no live prices are assumed.")
        with st.expander("What do these chart settings mean?"):
            st.markdown("**Stock symbol** is the listing’s short code. **Exchange** is where it is listed. "
                        "Each **price candle** shows the opening, highest, lowest and closing price for the chosen interval.")
        return
    if result["selection"] != (chart_market, chart_exchange, chart_symbol, chart_interval):
        st.info("The chart below is from your last loaded selection. Use ‘Explore this stock’ to apply the settings above.")
    candles, normalized = result["candles"], result["normalized"]
    st.caption(f"Source: {result['source']} · {len(candles)} candles · latest: {candles[-1].timestamp.isoformat()}")
    try:
        import plotly.graph_objects as go
        dark_chart = st.session_state.beru_theme_mode == "Dark"
        figure = go.Figure(data=[go.Candlestick(
            x=[c.timestamp for c in candles],
            open=[c.open for c in candles], high=[c.high for c in candles],
            low=[c.low for c in candles], close=[c.close for c in candles],
            name=normalized[2],
            increasing_line_color="#65d5aa" if dark_chart else "#2f7d63",
            decreasing_line_color="#ff93a4" if dark_chart else "#c0475c",
        )])
        grid = "#363e56" if dark_chart else "#e6e9f2"
        figure.update_layout(
            title=f"{normalized[0].upper()} {normalized[1]}:{normalized[2]} · {normalized[3]}",
            xaxis_title="Time", yaxis_title="Price",
            template="plotly_dark" if dark_chart else "plotly_white",
            height=510, margin=dict(l=20, r=20, t=55, b=20), xaxis_rangeslider_visible=False,
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#1a2033" if dark_chart else "#ffffff",
            font=dict(family="Arial, sans-serif", color="#e7e5f4" if dark_chart else "#2d3248"),
            xaxis=dict(gridcolor=grid), yaxis=dict(gridcolor=grid),
        )
        st.plotly_chart(figure, **wide(st.plotly_chart))
    except ImportError:
        st.error("Charts need Plotly. Install your existing project requirements.")
    except Exception as exc:
        error_details("The price chart couldn’t be displayed.", exc)
    with st.expander("Dig deeper: evidence & scenarios", expanded=False):
        if result["analysis_error"]:
            st.warning("The chart loaded, but the analysis could not be completed.")
            st.code(result["analysis_error"], language="text")
        elif result["analysis"] is not None:
            st.text(result["analysis"])


def render_tools() -> None:
    heading("Create tools · Advanced", "Give BERU a new skill.",
            "Add a custom Python tool to your existing tool library. The same builder checks and loads it, without restarting the app.")
    html('<div class="b-note">This is an advanced workspace. Only run Python code you trust; creating a tool executes code through your existing backend.</div>')
    if st.session_state.get("beru_forge_result") is not None:
        st.success(st.session_state.beru_forge_result)
    col1, col2 = st.columns([1.15, 1])
    with col1, panel("beru_panel_tool_form"):
        html('<div class="b-panel-title">Create a custom tool</div>'
             '<p class="b-panel-desc">Give it a name, explain its job, and add the Python function.</p>')
        f_name = field(st.text_input, "Tool name", key="beru_tool_name", default="generate_qr_code",
                       help="Use a Python function name, such as generate_qr_code.")
        f_desc = field(st.text_area, "What should it do?", key="beru_tool_description",
                       default="Generates a QR code image URL and returns access link.")
        f_code = field(st.text_area, "Python code", key="beru_tool_code", default=DEFAULT_TOOL_CODE, height=230)
        st.caption("This form keeps your original builder contract: one required text input, tested with ‘Beru AI AGENT’.")
        created = False
        if st.button("Create & test tool  ↗", key="beru_create_tool", type="primary", **wide(st.button)):
            try:
                with st.spinner("Building and testing your tool…"):
                    res = forge_new_tool(
                        name=f_name,
                        description=f_desc,
                        code=f_code,
                        parameters_schema={
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                            "required": ["text"],
                        },
                        sample_input={"text": "Beru AI AGENT"},
                    )
                st.session_state.beru_forge_result = res
                created = True
            except Exception as exc:
                error_details("Your tool couldn’t be created. Check the function name and code.", exc)
    with col2, panel("beru_panel_tool_library"):
        html(f'<div class="b-panel-title">Your custom tools <span style="opacity:.7">· {len(ACTIVE_FORGED_TOOLS)}</span></div>'
             '<p class="b-panel-desc">Tools registered by the existing BERU backend.</p>')
        if not ACTIVE_FORGED_TOOLS:
            empty_state("tools", "Room for your next idea.",
                        "Tools you create appear here. The example on the left generates a QR-code link.")
        for name, fn_path in list(ACTIVE_FORGED_TOOLS.items()):
            with st.expander(str(name)):
                st.markdown("**What it does:**")
                try:
                    from forge import _load_registry
                    reg = _load_registry()
                    desc = reg.get(name, {}).get("description", "No description provided.")
                    st.write(desc)
                    st.code(fn_path.read_text(encoding="utf-8"), language="python")
                except Exception as e:
                    st.error(f"Could not load tool source: {e}")
    if created:
        st.rerun()  # refresh the tool library with the new tool


def render_developer() -> None:
    heading("Developer workspace · Advanced", "From a good idea to something built.",
            "Browse your workspace, check code for security issues, or package a Python script using your existing build tools.")
    left, right = st.columns([1, 1])
    with left:
        with panel("beru_panel_files"):
            html('<div class="b-panel-title">Workspace files</div><p class="b-panel-desc">The files and folders in your configured project workspace.</p>')
            files = list_directory(WORKSPACE_DIR)
            if not files:
                st.info("No items are available in your workspace yet.")
            for f in files:
                try:
                    size = f"{f.stat().st_size:,} bytes"
                except OSError:
                    size = "Size unavailable"
                html(f'<div class="b-file"><span class="b-file-name">{h(f.name)}</span><small>{h(size)}</small></div>')
        with panel("beru_panel_compile"):
            html('<div class="b-panel-title">Make a Windows app</div>'
                 '<p class="b-panel-desc">Package a Python script as an .exe using the existing compiler. This needs the supported Windows build environment.</p>')
            script_to_compile = field(st.text_input, "Python script to package", key="beru_compile_script", default="app.py")
            if st.button("Build Windows app", key="beru_compile", type="primary", **wide(st.button)):
                try:
                    with st.spinner("Building your application…"):
                        res = compile_to_exe(script_to_compile)
                    st.session_state.beru_compile_result = (script_to_compile, res)
                except Exception as exc:
                    st.session_state.pop("beru_compile_result", None)
                    error_details("The build didn’t finish. Check the script path and build environment.", exc)
            if "beru_compile_result" in st.session_state:
                target, res = st.session_state.beru_compile_result
                st.caption(f"Build output for: {target}")
                st.code(str(res), language="text")
    with right, panel("beru_panel_audit"):
        html('<div class="b-panel-title">Check your code</div>'
             '<p class="b-panel-desc">Look for potential security issues in a file or folder. Your original static code-audit tool runs this check.</p>')
        target_to_audit = field(st.text_input, "File or folder to check", key="beru_audit_target", default="modes")
        if st.button("Check code security", key="beru_audit", type="primary", **wide(st.button)):
            try:
                with st.spinner("Checking your code…"):
                    report = audit_code_security(target_to_audit)
                st.session_state.beru_audit_result = (target_to_audit, report)
            except Exception as exc:
                st.session_state.pop("beru_audit_result", None)
                error_details("The code check couldn’t be completed. Verify the file or folder path.", exc)
        st.caption("A code scan can flag potential issues; it is not a guarantee that a project is secure.")
        if "beru_audit_result" in st.session_state:
            target, report = st.session_state.beru_audit_result
            st.caption(f"Report for: {target}")
            st.markdown(report)


def render_web_checks() -> None:
    heading("Website checks", "Get to know a website a little better.",
            "Check its public records, security certificate, open ports and security headers. Choose one check at a time and see the original results below.")
    html('<div class="b-note">Only assess websites and systems you own or have permission to test. The default is your existing scanme.nmap.org example.</div>')
    with panel("beru_panel_host"):
        target_host = field(st.text_input, "Website address or IP", key="beru_target_host", default="scanme.nmap.org",
                            help="Use a hostname such as example.com, or an IP address. The value is passed to the original tools unchanged.")
    checks = [
        ("dns", "Website records", "See where a domain points and inspect its public DNS records.", "Look up records", deep_dns_recon, "website", "blue"),
        ("ssl", "Security certificate", "Inspect the certificate used for an encrypted connection.", "Check certificate", inspect_ssl_certificate, "website", "mint"),
        ("ports", "Open ports", "Find which common network services respond on this host.", "Check open ports", audit_ports_and_services, "computer", ""),
        ("headers", "Security headers", "Review the security-related headers returned by the website.", "Check headers", audit_security_headers, "code", "peach"),
    ]
    for row in (checks[:2], checks[2:]):
        for col, (key, title, description, label, fn, symbol, tint) in zip(st.columns(2), row):
            with col, panel("beru_panel_check_" + key):
                html(f'<div class="b-icon {tint}">{icon(symbol)}</div>'
                     f'<div class="b-panel-title">{h(title)}</div><p class="b-panel-desc">{h(description)}</p>')
                if st.button(label + "  ↗", key="beru_check_" + key, **wide(st.button)):
                    if not target_host.strip():
                        st.warning("Please enter a website address first.")
                    else:
                        try:
                            with st.spinner("Running the selected website check…"):
                                output = fn(target_host)
                            st.session_state["beru_check_result_" + key] = (target_host, output)
                        except Exception as exc:
                            st.session_state.pop("beru_check_result_" + key, None)
                            error_details("This check couldn’t be completed. Verify the address and network connection.", exc)
                result = st.session_state.get("beru_check_result_" + key)
                if result is not None:
                    host, output = result
                    st.caption(f"Result for: {host}")
                    st.code(str(output), language="text")


def render_history() -> None:
    heading("Activity history", "Every step, in one place.",
            "Review local tool reliability, system health, user ratings, and metadata-only session timings.")
    with st.expander("Agent performance and feedback", expanded=True):
        st.caption("System health is a snapshot cached for up to 30 seconds. Tool reliability is cumulative; session traces include model, tool, and total response timings. Refresh this page to update.")
        st.markdown("**System health snapshot**")
        st.code(generate_system_health_briefing(), language="text")
        st.markdown("**Tool success and failure counts**")
        st.code(get_tool_optimizer_report(), language="text")
        try:
            summary = get_feedback_summary()
            helpful_rate = (summary["helpful"] / summary["total"] * 100) if summary["total"] else None
            rate_text = f"{helpful_rate:.1f}%" if helpful_rate is not None else "not enough feedback yet"
            st.caption(
                f"Answer ratings: {summary['total']} total · {summary['helpful']} helpful · "
                f"{summary['not_helpful']} needs improvement · helpful rate {rate_text}. "
                "Use the ratings as a review signal, not an automatic model-quality score."
            )
            if summary["reasons"]:
                st.caption("Improvement categories: " + ", ".join(
                    f"{reason.replace('_', ' ')} ({count})"
                    for reason, count in sorted(summary["reasons"].items())
                ))
        except Exception as exc:
            st.caption(f"Feedback metrics unavailable ({type(exc).__name__}).")
    try:
        trace_files = sorted(Path(TRACES_DIR).glob("*.jsonl"), key=os.path.getmtime, reverse=True)
    except OSError as exc:
        error_details("Saved activity files couldn’t be read.", exc)
        return
    if not trace_files:
        empty_state("history", "Nothing recorded here yet.",
                    "Saved sessions appear here when your existing backend writes activity logs.")
        return
    with panel("beru_panel_trace_picker"):
        selected_trace = field(st.selectbox, "Choose a saved session", key="beru_selected_trace",
                               options=[f.name for f in trace_files], default=trace_files[0].name)
        st.caption("Most recently updated first. This viewer never edits or deletes your logs.")
    trace_path = Path(TRACES_DIR) / selected_trace
    try:
        raw_lines = trace_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        error_details("This session file couldn’t be opened.", exc)
        return
    entries = []
    invalid_lines = []
    for line_number, line in enumerate(raw_lines, 1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            if not isinstance(entry, dict):
                raise ValueError("Expected an event object")
            entries.append(entry)
        except (json.JSONDecodeError, ValueError):
            invalid_lines.append(line_number)
    if invalid_lines:
        st.warning(f"Skipped {len(invalid_lines)} unreadable log line(s): " + ", ".join(map(str, invalid_lines))
                   + ". The original file has not been changed.")
    st.caption(f"{len(entries)} recorded events in {selected_trace}")
    if not entries:
        st.info("This file has no readable event entries yet.")
    for entry in entries:
        t_type = entry.get("type", "UNKNOWN")
        t_time = entry.get("time", "00:00:00")
        t_data = entry.get("data", {})
        with st.expander(f"{t_time}  ·  {str(t_type).replace('_', ' ').title()}"):
            st.caption(f"Original event type: {t_type}")
            show_json(t_data)


PAGE_RENDERERS = {
    "Assistant": render_assistant,
    "Stock explorer": render_market,
    "Create tools": render_tools,
    "Developer workspace": render_developer,
    "Website checks": render_web_checks,
    "Activity history": render_history,
}

PAGE_RENDERERS = {
    "Assistant": render_assistant,
    "Stock explorer": render_market,
    "Create tools": render_tools,
    "Developer workspace": render_developer,
    "Website checks": render_web_checks,
    "Activity history": render_history,
}

def run_page(name: str) -> None:
    """Render one page with ONLY this visitor's own API keys active."""
    try:
        with api_keys.applied(key_ui.user_keys()):
            PAGE_RENDERERS[name]()
    except api_keys.KeyScopeBusy:
        st.warning("BERU is finishing another request. Please wait a moment and try again.")
        st.button("Check again", key="beru_busy_retry")

init_state()
st.markdown(build_css(st.session_state.beru_theme_mode), unsafe_allow_html=True)
page = sidebar()
topbar(page)

# THE BYOK GATE
if key_ui.needs_setup():
    key_ui.render_key_manager()
else:
    key_ui.show_flash()
    run_page(page)
