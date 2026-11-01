"""api_keys.py - bring-your-own-keys support for BERU (no Streamlit import here).

What this module does
---------------------
* Defines the API keys BERU understands (KEY_SPECS).
* Validates what a visitor pastes (spaces, quotes, "NAME=value", formats).
* Optionally checks a key against the provider before saving it.
* Provides ``applied(keys)``: a context manager that makes ONLY the visitor's
  own keys visible to the backend while their request runs, and removes the
  server's own keys (for example from a leftover .env) so they are never used
  as a silent fallback. Everything is restored afterwards.

How keys reach the backend
--------------------------
The backend (config.py / gateway.py / modes/*) reads keys from the process
environment. ``applied`` therefore sets ``os.environ`` for the duration of a
request and ALSO patches module-level constants such as
``GROQ_API_KEY = os.getenv("GROQ_API_KEY")`` (and ``from config import X``
copies of them), which are otherwise frozen at import time. A process-wide
lock guarantees two visitors can never see each other's keys; requests from
different visitors therefore run one at a time inside one server process.

Keys are never written to disk, never logged, and never put in error text.

Run ``python api_keys.py --check`` in your project folder to see where the
backend consumes each key and whether anything is frozen at import time.
"""
from __future__ import annotations

import ast
import contextlib
import json
import os
import re
import sys
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, Iterator, List, Mapping, Optional, Tuple

PROJECT_DIR: Path = Path(__file__).resolve().parent


# --------------------------------------------------------------------------- #
# Key definitions
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class KeySpec:
    name: str          # environment variable name the backend reads
    label: str         # shown to the visitor
    group: str         # "llm" | "data" | "telegram"
    help: str
    url: str           # where the visitor can get one


KEY_SPECS: Tuple[KeySpec, ...] = (
    KeySpec("GROQ_API_KEY", "Groq API key", "llm",
            "Main cloud model provider.", "https://console.groq.com/keys"),
    KeySpec("GEMINI_API_KEY", "Google Gemini API key", "llm",
            "Fallback model provider.", "https://aistudio.google.com/app/apikey"),
    KeySpec("OPENROUTER_API_KEY", "OpenRouter API key", "llm",
            "Additional fallback model provider.", "https://openrouter.ai/keys"),
    KeySpec("ALPHA_VANTAGE_API_KEY", "Alpha Vantage API key", "data",
            "Stock explorer market data (daily/weekly history).",
            "https://www.alphavantage.co/support/#api-key"),
    KeySpec("VIRUSTOTAL_API_KEY", "VirusTotal API key", "data",
            "Reputation lookups in the security tools.",
            "https://www.virustotal.com/gui/my-apikey"),
    KeySpec("TELEGRAM_TOKEN", "Telegram bot token", "telegram",
            "Create a bot with @BotFather and paste its token.",
            "https://t.me/BotFather"),
    KeySpec("TELEGRAM_USER_ID", "Telegram user ID", "telegram",
            "Your numeric Telegram ID (for example from @userinfobot).",
            "https://t.me/userinfobot"),
)
KEY_NAMES: Tuple[str, ...] = tuple(s.name for s in KEY_SPECS)
LLM_KEY_NAMES: Tuple[str, ...] = tuple(s.name for s in KEY_SPECS if s.group == "llm")
SPEC_BY_NAME: Dict[str, KeySpec] = {s.name: s for s in KEY_SPECS}


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_WHITESPACE = re.compile(r"\s")
_TELEGRAM_TOKEN = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{30,}$")
_TELEGRAM_ID = re.compile(r"^-?\d{3,20}$")
_HEX64 = re.compile(r"^[A-Fa-f0-9]{64}$")
MAX_KEY_LEN = 512


def clean_value(name: str, raw: object) -> str:
    """Trim whitespace/quotes and accept a pasted ``NAME=value`` line."""
    if raw is None:
        return ""
    value = str(raw).strip()
    prefix = name + "="
    if value.upper().startswith(prefix.upper()):
        value = value[len(prefix):].strip()
    if value.lower().startswith("export ") and prefix.upper() in value.upper():
        value = value.split("=", 1)[1].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    return value


def validate(name: str, raw: object) -> Tuple[str, str, str]:
    """Return ``(clean_value, error, warning)``. Empty input -> ("", "", "")."""
    value = clean_value(name, raw)
    if not value:
        return "", "", ""
    if _CONTROL.search(value) or _WHITESPACE.search(value):
        return "", "This value contains spaces or line breaks. Paste only the key itself.", ""
    if len(value) > MAX_KEY_LEN:
        return "", "This value is too long to be an API key.", ""
    warning = ""
    if name == "TELEGRAM_TOKEN":
        if not _TELEGRAM_TOKEN.match(value):
            return "", "Telegram tokens look like 123456789:ABC... (digits, a colon, then letters/numbers).", ""
    elif name == "TELEGRAM_USER_ID":
        if not _TELEGRAM_ID.match(value):
            return "", "The Telegram user ID must be a number.", ""
    elif name == "GROQ_API_KEY" and not value.startswith("gsk_"):
        warning = "Groq keys normally start with gsk_ - double-check this one."
    elif name == "GEMINI_API_KEY" and not value.startswith("AIza"):
        warning = "Gemini keys normally start with AIza - double-check this one."
    elif name == "OPENROUTER_API_KEY" and not value.startswith("sk-or-"):
        warning = "OpenRouter keys normally start with sk-or- - double-check this one."
    elif name == "VIRUSTOTAL_API_KEY" and not _HEX64.match(value):
        warning = "VirusTotal keys are normally 64 hexadecimal characters."
    return value, "", warning


def mask(value: str) -> str:
    """Safe display form: never reveals more than the last 4 characters."""
    if not value:
        return ""
    if len(value) < 12:
        return "••••"
    return "••••" + value[-4:]


def is_ready(keys: Mapping[str, str], local_only: bool = False) -> bool:
    """BERU can start when at least one model key exists (or local-only mode)."""
    return bool(local_only) or any((keys.get(n) or "").strip() for n in LLM_KEY_NAMES)


def pair_warnings(keys: Mapping[str, str]) -> List[str]:
    has_token = bool(keys.get("TELEGRAM_TOKEN"))
    has_id = bool(keys.get("TELEGRAM_USER_ID"))
    if has_token != has_id:
        return ["Telegram needs BOTH the bot token and your user ID; alerts stay off until both are set."]
    return []


# --------------------------------------------------------------------------- #
# Optional provider check
# --------------------------------------------------------------------------- #
_UA = "Mozilla/5.0 (compatible; BERU-key-check/1.0)"


def _http_status(url: str, headers: Dict[str, str], timeout: float) -> Tuple[int, str]:
    """GET ``url``; return (status, first 2000 chars of body). 0 = network failure."""
    req = urllib.request.Request(url, headers={"User-Agent": _UA, **headers}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # fixed https hosts only
            return resp.status, resp.read(2000).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(2000).decode("utf-8", "replace")
        except Exception:
            body = ""
        return exc.code, body
    except Exception:  # URLError, timeout, SSL, ...  (never echo the exception: it can contain the URL)
        return 0, ""


def verify_key(name: str, value: str, timeout: float = 8.0) -> Tuple[str, str]:
    """Check one key. Returns (status, message); status is valid|invalid|unknown|unchecked."""
    if name == "GROQ_API_KEY":
        code, _ = _http_status("https://api.groq.com/openai/v1/models",
                               {"Authorization": f"Bearer {value}"}, timeout)
        bad = code == 401
    elif name == "OPENROUTER_API_KEY":
        code, _ = _http_status("https://openrouter.ai/api/v1/auth/key",
                               {"Authorization": f"Bearer {value}"}, timeout)
        bad = code == 401
    elif name == "GEMINI_API_KEY":
        code, body = _http_status("https://generativelanguage.googleapis.com/v1beta/models?pageSize=1",
                                  {"x-goog-api-key": value}, timeout)
        bad = code in (400, 401) and ("API_KEY_INVALID" in body or "API key not valid" in body or code == 401)
    elif name == "TELEGRAM_TOKEN":
        code, _ = _http_status(f"https://api.telegram.org/bot{value}/getMe", {}, timeout)
        bad = code in (401, 404)
    else:
        return "unchecked", "Format checked only (this provider has no free key-check endpoint)."
    if code == 200:
        return "valid", "Accepted by the provider."
    if bad:
        return "invalid", "The provider rejected this key. Check it and try again."
    if code == 0:
        return "unknown", "Could not reach the provider to verify it (network issue). Saved unverified."
    return "unknown", f"The provider answered with status {code}; the key could not be confirmed. Saved unverified."


# --------------------------------------------------------------------------- #
# Saving keys (pure function: easy to test, no UI)
# --------------------------------------------------------------------------- #
@dataclass
class SubmitResult:
    keys: Dict[str, str]
    saved: List[str]
    errors: List[Tuple[str, str]]
    warnings: List[Tuple[str, str]]


def submit_keys(
    existing: Mapping[str, str],
    submitted: Mapping[str, object],
    verify: bool = False,
    verifier: Optional[Callable[[str, str], Tuple[str, str]]] = None,
) -> SubmitResult:
    """Merge newly pasted values into ``existing``. Blank fields keep what is saved."""
    verifier = verifier or verify_key
    keys: Dict[str, str] = {n: v for n, v in existing.items() if n in SPEC_BY_NAME and v}
    saved: List[str] = []
    errors: List[Tuple[str, str]] = []
    warnings: List[Tuple[str, str]] = []
    for spec in KEY_SPECS:
        value, error, warning = validate(spec.name, submitted.get(spec.name))
        if error:
            errors.append((spec.name, error))
            continue
        if not value:
            continue
        if verify:
            try:
                status, message = verifier(spec.name, value)
            except Exception:
                status, message = "unknown", "Verification failed unexpectedly. Saved unverified."
            if status == "invalid":
                errors.append((spec.name, message))
                continue
            if status == "unknown":
                warnings.append((spec.name, message))
        if warning:
            warnings.append((spec.name, warning))
        keys[spec.name] = value
        saved.append(spec.name)
    for text in pair_warnings(keys):
        warnings.append(("TELEGRAM_TOKEN", text))
    return SubmitResult(keys=keys, saved=saved, errors=errors, warnings=warnings)


# --------------------------------------------------------------------------- #
# Source discovery: which module-level names hold a key frozen at import time
# --------------------------------------------------------------------------- #
_SKIP_DIRS = {"venv", ".venv", "env", ".git", "__pycache__", "node_modules", "site-packages",
              "dist-packages", ".streamlit", "workspace", ".idea", ".vscode", "build", "dist"}


def _project_py_files(root: Path) -> Iterator[Path]:
    for path in sorted(root.rglob("*.py")):
        rel_parts = path.relative_to(root).parts
        if any(p in _SKIP_DIRS or p.startswith(".") for p in rel_parts[:-1]):
            continue
        yield path


def _module_name(root: Path, path: Path) -> str:
    parts = list(path.relative_to(root).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _module_level(body: Iterable[ast.stmt]) -> Iterator[ast.stmt]:
    """Statements that run at import time (module body, plus if/try/with bodies)."""
    for node in body:
        yield node
        if isinstance(node, ast.If):
            yield from _module_level(node.body)
            yield from _module_level(node.orelse)
        elif isinstance(node, ast.Try):
            yield from _module_level(node.body)
            for handler in node.handlers:
                yield from _module_level(handler.body)
            yield from _module_level(node.orelse)
            yield from _module_level(node.finalbody)
        elif isinstance(node, (ast.With,)):
            yield from _module_level(node.body)


def _env_names_in(node: ast.AST) -> List[str]:
    """Managed key names that ``node`` reads through getenv/environ."""
    mentions_env = False
    found: List[str] = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute) and sub.attr in ("getenv", "environ"):
            mentions_env = True
        elif isinstance(sub, ast.Name) and sub.id in ("getenv", "environ"):
            mentions_env = True
        elif isinstance(sub, ast.Constant) and isinstance(sub.value, str) and sub.value in SPEC_BY_NAME:
            found.append(sub.value)
    return found if mentions_env else []


def _parse(path: Path) -> Optional[ast.Module]:
    try:
        return ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
    except (SyntaxError, ValueError, OSError):
        return None


def discover_aliases(root: Optional[Path] = None) -> Dict[str, Dict[str, str]]:
    """Map module name -> {attribute name: env var name} for import-time key constants.

    Finds ``X = os.getenv("GROQ_API_KEY")``-style assignments and the
    ``from config import X`` copies of them, so ``applied`` can patch both.
    """
    root = (root or PROJECT_DIR).resolve()
    defs: Dict[str, Dict[str, str]] = {}
    trees: Dict[str, ast.Module] = {}
    for path in _project_py_files(root):
        tree = _parse(path)
        if tree is None:
            continue
        mod = _module_name(root, path)
        trees[mod] = tree
        for node in _module_level(tree.body):
            targets: List[ast.expr] = []
            value: Optional[ast.expr] = None
            if isinstance(node, ast.Assign):
                targets, value = list(node.targets), node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [node.target], node.value
            if value is None or not isinstance(value, (ast.Call, ast.BoolOp, ast.IfExp, ast.Subscript)):
                continue
            names = _env_names_in(value)
            if not names:
                continue
            for target in targets:
                if isinstance(target, ast.Name):
                    defs.setdefault(mod, {})[target.id] = names[0]
    result: Dict[str, Dict[str, str]] = {m: dict(a) for m, a in defs.items()}
    for _ in range(3):  # follow `from a import X` chains
        changed = False
        for mod, tree in trees.items():
            package = mod.rsplit(".", 1)[0] if "." in mod else ""
            for node in _module_level(tree.body):
                if not isinstance(node, ast.ImportFrom) or not node.module and not node.level:
                    continue
                source = node.module or ""
                if node.level:
                    base = package.split(".") if package else []
                    base = base[: max(0, len(base) - (node.level - 1))]
                    source = ".".join(base + ([node.module] if node.module else []))
                src_aliases = result.get(source)
                if not src_aliases:
                    continue
                for imported in node.names:
                    env = src_aliases.get(imported.name)
                    local = imported.asname or imported.name
                    if env and result.setdefault(mod, {}).get(local) != env:
                        result[mod][local] = env
                        changed = True
        if not changed:
            break
    return result


_alias_cache: Optional[Dict[str, Dict[str, str]]] = None
_alias_lock = threading.Lock()


def _aliases() -> Dict[str, Dict[str, str]]:
    global _alias_cache
    with _alias_lock:
        if _alias_cache is None:
            try:
                _alias_cache = discover_aliases()
            except Exception:
                _alias_cache = {}
        return _alias_cache


# --------------------------------------------------------------------------- #
# Applying a visitor's keys for the duration of their request
# --------------------------------------------------------------------------- #
class KeyScopeBusy(RuntimeError):
    """Another visitor's request is still running; try again shortly."""


_SCOPE_LOCK = threading.RLock()


def _project_modules() -> List[Tuple[str, object]]:
    out: List[Tuple[str, object]] = []
    root = PROJECT_DIR.resolve()
    for name, mod in list(sys.modules.items()):
        if mod is None or name == __name__:
            continue
        file = getattr(mod, "__file__", None)
        if not file:
            continue
        try:
            path = Path(file).resolve()
        except (OSError, RuntimeError):
            continue
        if root not in path.parents:
            continue
        if any(p in ("site-packages", "dist-packages") for p in path.parts):
            continue
        out.append((name, mod))
    return out


@contextlib.contextmanager
def applied(keys: Mapping[str, str], timeout: float = 900.0) -> Iterator[None]:
    """Expose ONLY ``keys`` to the backend; restore the previous state on exit.

    Any managed key the visitor did not supply is removed for the duration, so
    the server's own keys can never be used on a visitor's behalf.
    """
    chosen: Dict[str, str] = {}
    for name in KEY_NAMES:
        value = keys.get(name)
        if isinstance(value, str) and value and not _CONTROL.search(value):
            chosen[name] = value

    if not _SCOPE_LOCK.acquire(timeout=timeout):
        raise KeyScopeBusy("Another request is still running.")
    saved_env: Dict[str, Optional[str]] = {n: os.environ.get(n) for n in KEY_NAMES}
    saved_attrs: List[Tuple[dict, str, object]] = []
    try:
        for name in KEY_NAMES:
            if name in chosen:
                os.environ[name] = chosen[name]
            else:
                os.environ.pop(name, None)

        aliases = _aliases()
        for mod_name, mod in _project_modules():
            namespace = getattr(mod, "__dict__", None)
            if not isinstance(namespace, dict):
                continue
            attr_to_env: Dict[str, str] = {n: n for n in KEY_NAMES}
            attr_to_env.update(aliases.get(mod_name, {}))
            for attr, env in attr_to_env.items():
                if attr not in namespace:
                    continue
                current = namespace[attr]
                if current is not None and not isinstance(current, str):
                    continue  # not a plain key constant (client object, dict, ...): leave alone
                saved_attrs.append((namespace, attr, current))
                if env in chosen:
                    namespace[attr] = chosen[env]
                else:
                    namespace[attr] = "" if isinstance(current, str) else None
        yield
    finally:
        for namespace, attr, original in reversed(saved_attrs):
            try:
                namespace[attr] = original
            except Exception:
                pass
        for name, original in saved_env.items():
            try:
                if original is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = original
            except Exception:
                pass
        _SCOPE_LOCK.release()


# --------------------------------------------------------------------------- #
# Deployment self-check (python api_keys.py --check)
# --------------------------------------------------------------------------- #
def deployment_check(root: Optional[Path] = None) -> str:
    root = (root or PROJECT_DIR).resolve()
    lines: List[str] = [f"BERU key check for: {root}", ""]

    env_file = root / ".env"
    if env_file.exists():
        lines.append("[!] A .env file exists here. Do NOT ship it to the server/image; "
                     "visitors must bring their own keys.")
        gitignore = root / ".gitignore"
        ignored = gitignore.exists() and any(
            ln.strip() in (".env", "/.env", ".env*") for ln in gitignore.read_text(errors="replace").splitlines())
        lines.append("    .env is " + ("listed" if ignored else "NOT listed (add it!)") + " in .gitignore.")
    else:
        lines.append("[ok] No .env file in the project folder.")

    present = [n for n in KEY_NAMES if os.environ.get(n)]
    if present:
        lines.append("[!] These keys are set in THIS process environment (they would be stripped "
                     "per request by the app, but remove them from the host too): " + ", ".join(present))
    lines.append("")

    aliases = discover_aliases(root)
    frozen = {m: a for m, a in aliases.items() if a}
    if frozen:
        lines.append("Import-time key constants found (the app patches these automatically per request):")
        for mod, attrs in sorted(frozen.items()):
            for attr, env in sorted(attrs.items()):
                lines.append(f"    {mod}.{attr}  <-  {env}")
    else:
        lines.append("No import-time key constants found.")
    lines.append("")

    problems: List[str] = []
    for path in _project_py_files(root):
        if path.name == Path(__file__).name:
            continue
        tree = _parse(path)
        if tree is None:
            continue
        mod = _module_name(root, path)
        local_names = set(aliases.get(mod, {}))
        for node in _module_level(tree.body):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                                 ast.Import, ast.ImportFrom, ast.If, ast.Try, ast.With)):
                continue
            is_alias_def = (isinstance(node, (ast.Assign, ast.AnnAssign))
                            and any(isinstance(t, ast.Name) and t.id in local_names
                                    for t in (node.targets if isinstance(node, ast.Assign) else [node.target])))
            if is_alias_def:
                continue
            uses = [s for s in ast.walk(node)
                    if (isinstance(s, ast.Constant) and isinstance(s.value, str) and s.value in SPEC_BY_NAME)
                    or (isinstance(s, ast.Name) and s.id in local_names)
                    or (isinstance(s, ast.Name) and s.id in SPEC_BY_NAME)]
            if uses:
                problems.append(f"    {path.relative_to(root)}:{node.lineno}")
    if problems:
        lines.append("[!] Module-level code that uses a key outside a simple constant (for example a client "
                     "created at import time). It will keep the server's key, not the visitor's. Move it "
                     "inside a function that reads the key when called:")
        lines.extend(problems)
    else:
        lines.append("[ok] No import-time clients or other frozen key uses found.")
    lines.append("")

    lines.append("Where each key is read in the source:")
    pattern_cache = {n: re.compile(r"\b" + re.escape(n) + r"\b") for n in KEY_NAMES}
    for name in KEY_NAMES:
        hits: List[str] = []
        for path in _project_py_files(root):
            if path.name == Path(__file__).name or path.name.startswith("test_"):
                continue
            try:
                for number, text in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if pattern_cache[name].search(text):
                        hits.append(f"{path.relative_to(root)}:{number}")
            except OSError:
                continue
        lines.append(f"  {name}: " + (", ".join(hits[:8]) + (" ..." if len(hits) > 8 else "") if hits else "not referenced"))
    return "\n".join(lines)


if __name__ == "__main__":
    target = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else None
    if "--check" in sys.argv:
        print(deployment_check(target))
    else:
        print(json.dumps({"keys": list(KEY_NAMES)}, indent=2))
