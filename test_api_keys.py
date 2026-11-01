"""Tests for api_keys.py / key_ui.py.  Run: python -m pytest test_api_keys.py -q"""
import importlib
import os
import sys
import textwrap
import threading
import time
import types
from pathlib import Path
from unittest import mock

import pytest

import api_keys


# ----------------------------------------------------------------- validation
def test_clean_and_validate_basics():
    assert api_keys.validate("GROQ_API_KEY", "")[0] == ""
    assert api_keys.validate("GROQ_API_KEY", None) == ("", "", "")
    assert api_keys.validate("GROQ_API_KEY", "  gsk_abc123  ")[0] == "gsk_abc123"
    assert api_keys.validate("GROQ_API_KEY", '"gsk_abc123"')[0] == "gsk_abc123"
    assert api_keys.validate("GROQ_API_KEY", "'gsk_abc123'")[0] == "gsk_abc123"
    assert api_keys.validate("GROQ_API_KEY", "GROQ_API_KEY=gsk_abc123")[0] == "gsk_abc123"
    assert api_keys.validate("GROQ_API_KEY", 'export GROQ_API_KEY="gsk_abc123"')[0] == "gsk_abc123"


def test_rejects_whitespace_control_and_huge():
    for bad in ("gsk abc", "gsk_a\nb", "gsk_a\x00b", "a\tb"):
        value, err, _ = api_keys.validate("GROQ_API_KEY", bad)
        assert value == "" and err
    assert api_keys.validate("GROQ_API_KEY", "g" * 600)[1]


def test_prefix_mismatch_is_warning_not_error():
    value, err, warn = api_keys.validate("GROQ_API_KEY", "notgsk_1234")
    assert value == "notgsk_1234" and not err and warn
    assert api_keys.validate("GROQ_API_KEY", "gsk_ok")[2] == ""


def test_telegram_strict_formats():
    token = "123456789:" + "A" * 35
    assert api_keys.validate("TELEGRAM_TOKEN", token)[0] == token
    assert api_keys.validate("TELEGRAM_TOKEN", "nope")[1]
    assert api_keys.validate("TELEGRAM_USER_ID", "123456789")[0] == "123456789"
    assert api_keys.validate("TELEGRAM_USER_ID", "-1001234567890")[0] == "-1001234567890"
    assert api_keys.validate("TELEGRAM_USER_ID", "abc")[1]


def test_mask_never_leaks():
    assert api_keys.mask("") == ""
    assert api_keys.mask("short") == "••••"
    secret = "gsk_" + "x" * 40 + "WXYZ"
    shown = api_keys.mask(secret)
    assert shown.endswith("WXYZ") and secret[:-4] not in shown


def test_is_ready():
    assert not api_keys.is_ready({})
    assert not api_keys.is_ready({"VIRUSTOTAL_API_KEY": "x" * 64})
    assert api_keys.is_ready({"GEMINI_API_KEY": "AIza1"})
    assert api_keys.is_ready({}, local_only=True)
    assert not api_keys.is_ready({"GROQ_API_KEY": "   "})


# ---------------------------------------------------------------- submit_keys
def test_submit_merges_and_keeps_blank():
    existing = {"GROQ_API_KEY": "gsk_old"}
    res = api_keys.submit_keys(existing, {"GROQ_API_KEY": "", "GEMINI_API_KEY": "AIzaNEW"})
    assert res.keys == {"GROQ_API_KEY": "gsk_old", "GEMINI_API_KEY": "AIzaNEW"}
    assert res.saved == ["GEMINI_API_KEY"] and not res.errors
    assert existing == {"GROQ_API_KEY": "gsk_old"}  # input not mutated


def test_submit_replaces_existing():
    res = api_keys.submit_keys({"GROQ_API_KEY": "gsk_old"}, {"GROQ_API_KEY": "gsk_new"})
    assert res.keys["GROQ_API_KEY"] == "gsk_new"


def test_submit_invalid_key_not_stored_and_valid_ones_still_saved():
    def verifier(name, value):
        return ("invalid", "rejected") if name == "GROQ_API_KEY" else ("valid", "ok")

    res = api_keys.submit_keys({}, {"GROQ_API_KEY": "gsk_bad", "GEMINI_API_KEY": "AIzaGood"},
                               verify=True, verifier=verifier)
    assert "GROQ_API_KEY" not in res.keys and res.keys["GEMINI_API_KEY"] == "AIzaGood"
    assert [n for n, _ in res.errors] == ["GROQ_API_KEY"]


def test_submit_unknown_status_saves_with_warning_and_verifier_crash_is_safe():
    res = api_keys.submit_keys({}, {"GROQ_API_KEY": "gsk_x"}, verify=True,
                               verifier=lambda n, v: ("unknown", "offline"))
    assert res.keys["GROQ_API_KEY"] == "gsk_x" and res.warnings

    def boom(n, v):
        raise RuntimeError("secret gsk_x leaked?")

    res = api_keys.submit_keys({}, {"GROQ_API_KEY": "gsk_x"}, verify=True, verifier=boom)
    assert res.keys["GROQ_API_KEY"] == "gsk_x"
    assert all("gsk_x" not in m for _, m in res.warnings)


def test_submit_telegram_pair_warning():
    res = api_keys.submit_keys({}, {"TELEGRAM_USER_ID": "123456"})
    assert any("BOTH" in m for _, m in res.warnings)
    token = "123456789:" + "A" * 35
    res = api_keys.submit_keys({}, {"TELEGRAM_USER_ID": "123456", "TELEGRAM_TOKEN": token})
    assert not any("BOTH" in m for _, m in res.warnings)


def test_verify_key_status_mapping():
    with mock.patch.object(api_keys, "_http_status", return_value=(200, "")):
        assert api_keys.verify_key("GROQ_API_KEY", "k")[0] == "valid"
    with mock.patch.object(api_keys, "_http_status", return_value=(401, "")):
        assert api_keys.verify_key("GROQ_API_KEY", "k")[0] == "invalid"
        assert api_keys.verify_key("OPENROUTER_API_KEY", "k")[0] == "invalid"
    with mock.patch.object(api_keys, "_http_status", return_value=(0, "")):
        assert api_keys.verify_key("GROQ_API_KEY", "k")[0] == "unknown"
    with mock.patch.object(api_keys, "_http_status", return_value=(429, "")):
        assert api_keys.verify_key("GROQ_API_KEY", "k")[0] == "unknown"
    with mock.patch.object(api_keys, "_http_status", return_value=(400, '{"error":"API_KEY_INVALID"}')):
        assert api_keys.verify_key("GEMINI_API_KEY", "k")[0] == "invalid"
    with mock.patch.object(api_keys, "_http_status", return_value=(400, "something else")):
        assert api_keys.verify_key("GEMINI_API_KEY", "k")[0] == "unknown"
    with mock.patch.object(api_keys, "_http_status", return_value=(404, "")):
        assert api_keys.verify_key("TELEGRAM_TOKEN", "1:abc")[0] == "invalid"
    assert api_keys.verify_key("VIRUSTOTAL_API_KEY", "k")[0] == "unchecked"


def test_http_status_network_failure_returns_zero_and_no_exception():
    with mock.patch("urllib.request.urlopen", side_effect=OSError("boom https://x/botSECRET")):
        assert api_keys._http_status("https://example.invalid", {}, 1.0) == (0, "")


# --------------------------------------------------- fake backend project dir
@pytest.fixture()
def fake_project(tmp_path, monkeypatch):
    """A tiny backend that reads keys in the three common ways."""
    (tmp_path / "modes").mkdir()
    (tmp_path / "modes" / "__init__.py").write_text("")
    (tmp_path / "config.py").write_text(textwrap.dedent('''
        import os
        GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
        GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
        VT = os.getenv("VIRUSTOTAL_API_KEY") or ""
        SETTINGS = {"x": os.getenv("OPENROUTER_API_KEY")}
        TIMEOUT = 30
    '''))
    (tmp_path / "gateway.py").write_text(textwrap.dedent('''
        import os
        from config import GROQ_API_KEY, GEMINI_KEY as GK
        import config

        def call_time_env():
            return os.getenv("OPENROUTER_API_KEY")

        def frozen_copy():
            return GROQ_API_KEY

        def aliased_copy():
            return GK

        def via_config():
            return config.VT
    '''))
    (tmp_path / "modes" / "market.py").write_text(textwrap.dedent('''
        import os
        def av():
            return os.environ.get("ALPHA_VANTAGE_API_KEY")
    '''))
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(api_keys, "PROJECT_DIR", tmp_path)
    monkeypatch.setattr(api_keys, "_alias_cache", None)
    for name in api_keys.KEY_NAMES:
        monkeypatch.delenv(name, raising=False)
    for m in ("config", "gateway", "modes", "modes.market"):
        sys.modules.pop(m, None)
    yield tmp_path
    for m in ("config", "gateway", "modes", "modes.market"):
        sys.modules.pop(m, None)


def _load(monkeypatch=None):
    config = importlib.import_module("config")
    gateway = importlib.import_module("gateway")
    market = importlib.import_module("modes.market")
    return config, gateway, market


def test_alias_discovery(fake_project):
    aliases = api_keys.discover_aliases(fake_project)
    assert aliases["config"]["GROQ_API_KEY"] == "GROQ_API_KEY"
    assert aliases["config"]["GEMINI_KEY"] == "GEMINI_API_KEY"
    assert aliases["config"]["VT"] == "VIRUSTOTAL_API_KEY"
    assert "SETTINGS" not in aliases["config"]  # dict constants are not touched
    assert aliases["gateway"]["GK"] == "GEMINI_API_KEY"  # `from config import X as GK`
    assert aliases["gateway"]["GROQ_API_KEY"] == "GROQ_API_KEY"


def test_applied_sets_visitor_keys_everywhere_then_restores(fake_project, monkeypatch):
    # Server owner's keys exist (leftover .env) BEFORE modules are imported.
    monkeypatch.setenv("GROQ_API_KEY", "OWNER_GROQ")
    monkeypatch.setenv("GEMINI_API_KEY", "OWNER_GEMINI")
    monkeypatch.setenv("OPENROUTER_API_KEY", "OWNER_OR")
    monkeypatch.setenv("VIRUSTOTAL_API_KEY", "OWNER_VT")
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "OWNER_AV")
    config, gateway, market = _load()
    assert gateway.frozen_copy() == "OWNER_GROQ"  # proves the constant really is frozen

    visitor = {"GROQ_API_KEY": "gsk_VISITOR", "GEMINI_API_KEY": "AIza_VISITOR"}
    with api_keys.applied(visitor):
        assert gateway.frozen_copy() == "gsk_VISITOR"
        assert gateway.aliased_copy() == "AIza_VISITOR"
        assert config.GROQ_API_KEY == "gsk_VISITOR"
        assert os.getenv("GROQ_API_KEY") == "gsk_VISITOR"
        # keys the visitor did NOT provide must not fall back to the owner's:
        assert gateway.call_time_env() is None
        assert gateway.via_config() == ""          # str constant -> empty string
        assert market.av() is None
        assert config.SETTINGS == {"x": "OWNER_OR"}  # untouched non-string constant
        assert config.TIMEOUT == 30

    # Everything restored.
    assert gateway.frozen_copy() == "OWNER_GROQ"
    assert gateway.aliased_copy() == "OWNER_GEMINI"
    assert gateway.call_time_env() == "OWNER_OR"
    assert gateway.via_config() == "OWNER_VT"
    assert market.av() == "OWNER_AV"
    assert os.environ["GROQ_API_KEY"] == "OWNER_GROQ"


def test_applied_with_no_server_keys_deployed_case(fake_project):
    config, gateway, market = _load()
    assert gateway.frozen_copy() == "" and gateway.call_time_env() is None
    with api_keys.applied({"GROQ_API_KEY": "gsk_V", "ALPHA_VANTAGE_API_KEY": "AVKEY"}):
        assert gateway.frozen_copy() == "gsk_V"
        assert market.av() == "AVKEY"
        assert config.GEMINI_KEY is None  # None constant stays None, not ""
    assert gateway.frozen_copy() == "" and market.av() is None
    assert "GROQ_API_KEY" not in os.environ


def test_applied_restores_after_exception_and_base_exception(fake_project):
    config, gateway, market = _load()

    class Rerun(BaseException):  # like Streamlit's st.rerun / st.stop
        pass

    for exc in (ValueError("x"), Rerun()):
        with pytest.raises(type(exc)):
            with api_keys.applied({"GROQ_API_KEY": "gsk_V"}):
                assert gateway.frozen_copy() == "gsk_V"
                raise exc
        assert gateway.frozen_copy() == "" and "GROQ_API_KEY" not in os.environ
        # lock must be free again
        assert api_keys._SCOPE_LOCK.acquire(blocking=False)
        api_keys._SCOPE_LOCK.release()


def test_applied_ignores_unknown_and_malformed_values(fake_project):
    _load()
    with api_keys.applied({"GROQ_API_KEY": "bad\x00value", "NOT_A_KEY": "zzz", "GEMINI_API_KEY": 123}):
        assert "GROQ_API_KEY" not in os.environ
        assert "NOT_A_KEY" not in os.environ
        assert "GEMINI_API_KEY" not in os.environ


def test_nested_applied_is_reentrant(fake_project):
    _load()
    with api_keys.applied({"GROQ_API_KEY": "gsk_A"}):
        with api_keys.applied({"GROQ_API_KEY": "gsk_A"}):
            assert os.environ["GROQ_API_KEY"] == "gsk_A"
        assert os.environ["GROQ_API_KEY"] == "gsk_A"
    assert "GROQ_API_KEY" not in os.environ


def test_two_visitors_never_see_each_others_keys(fake_project):
    config, gateway, market = _load()
    problems = []
    barrier = threading.Barrier(2)

    def visitor(tag):
        barrier.wait()
        for _ in range(15):
            with api_keys.applied({"GROQ_API_KEY": f"gsk_{tag}"}):
                for _ in range(5):
                    seen = {gateway.frozen_copy(), os.getenv("GROQ_API_KEY"), config.GROQ_API_KEY}
                    if seen != {f"gsk_{tag}"}:
                        problems.append((tag, seen))
                    time.sleep(0.001)

    threads = [threading.Thread(target=visitor, args=(t,)) for t in ("A", "B")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert not problems
    assert "GROQ_API_KEY" not in os.environ


def test_busy_timeout_raises_keyscopebusy(fake_project):
    _load()
    started, release = threading.Event(), threading.Event()

    def hold():
        with api_keys.applied({"GROQ_API_KEY": "gsk_A"}):
            started.set()
            release.wait(10)

    t = threading.Thread(target=hold)
    t.start()
    assert started.wait(5)
    try:
        with pytest.raises(api_keys.KeyScopeBusy):
            with api_keys.applied({"GROQ_API_KEY": "gsk_B"}, timeout=0.2):
                pass
    finally:
        release.set()
        t.join(10)
    assert "GROQ_API_KEY" not in os.environ


def test_third_party_modules_are_not_touched(fake_project):
    fake = types.ModuleType("somelib")
    fake.GROQ_API_KEY = "LIB_VALUE"
    fake.__file__ = "/usr/lib/python3/site-packages/somelib.py"
    sys.modules["somelib"] = fake
    try:
        with api_keys.applied({"GROQ_API_KEY": "gsk_V"}):
            assert fake.GROQ_API_KEY == "LIB_VALUE"
    finally:
        sys.modules.pop("somelib", None)


def test_deployment_check_reports(fake_project):
    (fake_project / ".env").write_text("GROQ_API_KEY=abc\n")
    (fake_project / "client.py").write_text(
        'import os\nfrom config import GROQ_API_KEY\nclient = make_client(api_key=os.getenv("GROQ_API_KEY"))\n')
    report = api_keys.deployment_check(fake_project)
    assert ".env" in report and "NOT listed" in report
    assert "config.GEMINI_KEY" in report
    assert "client.py:3" in report  # client created at import time is flagged
    assert "GROQ_API_KEY" in report


# --------------------------------------------------------------- key_ui smoke
class _State(dict):
    __getattr__ = dict.get

    def __setattr__(self, k, v):
        self[k] = v


@pytest.fixture()
def ui(monkeypatch):
    fake_st = mock.MagicMock()
    fake_st.session_state = _State()
    fake_st.text_input.return_value = ""
    fake_st.form_submit_button.return_value = False
    fake_st.checkbox.return_value = False
    fake_st.columns.side_effect = lambda spec: [mock.MagicMock() for _ in range(spec if isinstance(spec, int) else len(spec))]
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    sys.modules.pop("key_ui", None)
    module = importlib.import_module("key_ui")
    yield module, fake_st
    sys.modules.pop("key_ui", None)


def test_ui_needs_setup_flow(ui):
    key_ui, st = ui
    assert key_ui.needs_setup()                      # no keys yet -> gate
    st.session_state[key_ui.KEYS_STATE] = {"GROQ_API_KEY": "gsk_x"}
    assert not key_ui.needs_setup()
    key_ui._open_manager()
    assert key_ui.needs_setup()
    key_ui._close_manager()
    assert not key_ui.needs_setup()
    key_ui._remove_all()
    assert key_ui.needs_setup() and key_ui.user_keys() == {}
    key_ui._use_local_only()
    assert not key_ui.needs_setup()


def test_ui_remove_single_key(ui):
    key_ui, st = ui
    st.session_state[key_ui.KEYS_STATE] = {"GROQ_API_KEY": "gsk_x", "GEMINI_API_KEY": "AIza"}
    key_ui._remove_key("GROQ_API_KEY")
    assert key_ui.user_keys() == {"GEMINI_API_KEY": "AIza"}
    key_ui._remove_key("NOT_THERE")  # no crash


def test_ui_renders_without_crashing_and_saves(ui):
    key_ui, st = ui
    key_ui.render_sidebar_keys()
    key_ui.render_key_manager()                     # empty state renders

    st.form_submit_button.return_value = True
    st.text_input.side_effect = lambda label, **kw: "gsk_abc" if label.startswith("Groq") else ""
    st.rerun.side_effect = RuntimeError("rerun")    # st.rerun raises in real Streamlit
    with pytest.raises(RuntimeError, match="rerun"):
        key_ui.render_key_manager()
    assert st.session_state[key_ui.KEYS_STATE] == {"GROQ_API_KEY": "gsk_abc"}
    assert st.session_state[key_ui.SHOW_STATE] is False
    assert "Groq" in st.session_state[key_ui.FLASH_STATE]
    assert "gsk_abc" not in st.session_state[key_ui.FLASH_STATE]
    key_ui.show_flash()
    assert key_ui.FLASH_STATE not in st.session_state


def test_ui_bad_input_shows_error_not_saved(ui):
    key_ui, st = ui
    st.form_submit_button.return_value = True
    st.text_input.side_effect = lambda label, **kw: "123 456" if label.startswith("Telegram user") else ""
    st.rerun.side_effect = RuntimeError("rerun")
    with pytest.raises(RuntimeError):
        key_ui.render_key_manager()
    assert key_ui.user_keys() == {}
    assert st.session_state[key_ui.RESULT_STATE]["errors"]
    st.rerun.side_effect = None
    st.form_submit_button.return_value = False
    key_ui.render_key_manager()                      # shows the stored error once
    st.error.assert_called()
    assert key_ui.RESULT_STATE not in st.session_state
