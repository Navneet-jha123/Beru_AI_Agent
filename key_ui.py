"""key_ui.py - Streamlit screens for visitor-supplied API keys.

Keys live only in ``st.session_state`` (server memory for this one browser
session). They are never written to disk or logged, and they disappear when
the session ends or the visitor presses "Remove all keys".
"""
from __future__ import annotations

from typing import Any, Dict

import streamlit as st

import api_keys

KEYS_STATE = "beru_user_keys"      # {ENV_NAME: value}
LOCAL_STATE = "beru_local_only"    # True = no cloud keys, local model only
SHOW_STATE = "beru_show_keys"      # True = show the key manager page
FLASH_STATE = "beru_key_flash"     # one-time message after saving
RESULT_STATE = "beru_key_result"   # one-time save result shown on the key page

_GROUP_TITLES = {
    "llm": ("1. AI Model Providers (Groq is REQUIRED. Others are optional for fallbacks)", 
            "Add your Groq key to start. If Groq goes down, BERU will automatically use Gemini or OpenRouter if you provide them."),
    "data": ("2. Optional Data Services", 
             "Only add these if you want to use the Stock Explorer (Alpha Vantage) or Malware Scanner (VirusTotal)."),
    "telegram": ("3. Telegram Alerts (Optional)", 
                 "Only add these if you want BERU to send you alerts on Telegram. Both fields are required together."),
}


def _wide() -> Dict[str, Any]:
    import inspect
    try:
        params = inspect.signature(st.button).parameters
    except (TypeError, ValueError):
        return {}
    if "width" in params:
        return {"width": "stretch"}
    if "use_container_width" in params:
        return {"use_container_width": True}
    return {}


def _supports(fn: Any, param: str) -> bool:
    import inspect
    try:
        return param in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------- state access
def user_keys() -> Dict[str, str]:
    """This visitor's keys (a plain dict; empty until they add some)."""
    if KEYS_STATE not in st.session_state or not isinstance(st.session_state[KEYS_STATE], dict):
        st.session_state[KEYS_STATE] = {}
    return st.session_state[KEYS_STATE]


def local_only() -> bool:
    return bool(st.session_state.get(LOCAL_STATE, False))


def needs_setup() -> bool:
    """True when BERU must show the key manager instead of the workspace."""
    return bool(st.session_state.get(SHOW_STATE, False)) or not api_keys.is_ready(user_keys(), local_only())


# ------------------------------------------------------------------- callbacks
def _open_manager() -> None:
    st.session_state[SHOW_STATE] = True


def _close_manager() -> None:
    st.session_state[SHOW_STATE] = False


def _use_local_only() -> None:
    st.session_state[LOCAL_STATE] = True
    st.session_state[SHOW_STATE] = False


def _remove_key(name: str) -> None:
    keys = dict(user_keys())
    keys.pop(name, None)
    st.session_state[KEYS_STATE] = keys


def _remove_all() -> None:
    st.session_state[KEYS_STATE] = {}
    st.session_state[LOCAL_STATE] = False
    st.session_state[SHOW_STATE] = True


# --------------------------------------------------------------------- screens
def render_sidebar_keys() -> None:
    """Small status block in the sidebar with a button to open the key manager."""
    keys = user_keys()
    with st.expander("API keys", expanded=False):
        if keys:
            for spec in api_keys.KEY_SPECS:
                if spec.name in keys:
                    st.caption(f"✓ {spec.label}")
        if local_only():
            st.caption("Local model only (no cloud keys).")
        if not keys and not local_only():
            st.caption("No keys added yet.")
        st.caption("Stored for this browser session only. Never saved to disk.")
        st.button("Manage API keys", key="beru_open_keys", on_click=_open_manager, **_wide())


def show_flash() -> None:
    message = st.session_state.pop(FLASH_STATE, None)
    if message:
        st.success(message)


def render_key_manager() -> None:
    state = st.session_state
    keys = user_keys()
    ready = api_keys.is_ready(keys, local_only())

    st.markdown("### Connect your own API keys" if not ready else "### Your API keys")
    st.write(
        "BERU runs on **your** accounts. Paste your keys below. "
        "**You ONLY need a Groq API key to use the full chat and developer features.** "
        "The other keys are 100% optional and only unlock extra features (like stock data)."
    )
    st.info("🔒 **Privacy:** Keys are kept in this browser session's memory on the server, are never written to disk or logs, and are forgotten when you close the session.")

    result = state.pop(RESULT_STATE, None)
    if result:
        for name, message in result["errors"]:
            st.error(f"{api_keys.SPEC_BY_NAME[name].label}: {message}")
        for name, message in result["warnings"]:
            st.warning(f"{api_keys.SPEC_BY_NAME[name].label}: {message}")
        if result["saved"]:
            st.success("Saved: " + ", ".join(api_keys.SPEC_BY_NAME[n].label for n in result["saved"]) + ".")
        elif result["empty"] and not result["errors"]:
            st.info("Nothing to save - all fields were empty.")

    saved_names = [spec for spec in api_keys.KEY_SPECS if spec.name in keys]
    if saved_names:
        st.markdown("**Saved in this session**")
        for spec in saved_names:
            label_col, button_col = st.columns([3, 1])
            with label_col:
                st.write(f"✓ {spec.label}  `{api_keys.mask(keys[spec.name])}`")
            with button_col:
                st.button("Remove", key=f"beru_rm_{spec.name}", on_click=_remove_key,
                          args=(spec.name,), **_wide())

    submitted_values: Dict[str, str] = {}
    with st.form("beru_keys_form", clear_on_submit=True):
        for group in ("llm", "data", "telegram"):
            title, note = _GROUP_TITLES[group]
            st.markdown(f"**{title}**")
            st.caption(note)
            for spec in api_keys.KEY_SPECS:
                if spec.group != group:
                    continue
                already = spec.name in keys
                placeholder = (f"Saved ({api_keys.mask(keys[spec.name])}). Paste a new one to replace."
                               if already else "Paste your key here")
                extra = {"autocomplete": "off"} if _supports(st.text_input, "autocomplete") else {}
                
                # Add visual labels so users know Groq is the only requirement
                label = spec.label
                if spec.name == "GROQ_API_KEY":
                    label = "🔴 Groq API key (REQUIRED)"
                elif group == "llm":
                    label = f"🟢 {spec.label} (Optional Fallback)"
                else:
                    label = f"⚪ {spec.label} (Optional)"

                submitted_values[spec.name] = st.text_input(
                    label, type="password", key=f"beru_keyin_{spec.name}",
                    placeholder=placeholder, help=f"{spec.help} Get one: {spec.url}",
                    **extra,
                ) or ""
        verify = st.checkbox("Check keys with each provider before saving", value=True,
                             key="beru_keys_verify",
                             help="Sends one small read-only request to the provider. Never stored.")
        pressed = st.form_submit_button("Save keys", type="primary")

    if pressed:
        with st.spinner("Checking your keys…" if verify else "Saving…"):
            result = api_keys.submit_keys(keys, submitted_values, verify=verify)
        state[KEYS_STATE] = result.keys
        clean = not result.errors and not result.warnings
        if result.saved and clean and api_keys.is_ready(result.keys, local_only()):
            state[SHOW_STATE] = False
            state[FLASH_STATE] = ("Saved: " + ", ".join(api_keys.SPEC_BY_NAME[n].label for n in result.saved)
                                  + ". BERU is ready.")
        else:
            state[RESULT_STATE] = {
                "saved": list(result.saved), "errors": list(result.errors),
                "warnings": list(result.warnings), "empty": not submitted_values or not any(
                    (v or "").strip() for v in submitted_values.values()),
            }
        st.rerun()

    st.divider()
    if ready:
        st.button("Back to my workspace", key="beru_keys_done", type="primary",
                  on_click=_close_manager, **_wide())
    else:
        st.caption("Add at least one AI model key to start, or run on a local model instead.")
        st.button("Use a local model only (no cloud keys)", key="beru_keys_local",
                  on_click=_use_local_only, **_wide(),
                  help="Needs a local model server configured by the host (LOCAL_LLM_URL).")
    if keys or local_only():
        st.button("Remove all my keys", key="beru_keys_clear", on_click=_remove_all, **_wide())
