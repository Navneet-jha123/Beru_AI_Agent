"""
config.py - Centralized configuration for BERU AI AGENT.
Auto-detects credentials from local or parent .env files.
Configures multi-tier neural models, performance limits, and workspace storage.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR: Path = Path(__file__).resolve().parent
PARENT_DIR: Path = BASE_DIR.parent

# 1. Load environment variables (current dir first, then parent dir)
if (BASE_DIR / ".env").exists():
    load_dotenv(BASE_DIR / ".env")
elif (PARENT_DIR / ".env").exists():
    load_dotenv(PARENT_DIR / ".env")
else:
    load_dotenv()

# 2. API Credentials
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "").strip()
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "").strip()
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "").strip()
TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_TOKEN", "").strip()
TELEGRAM_USER_ID: str = os.getenv("TELEGRAM_USER_ID", "").strip()
LOCAL_LLM_URL: str = os.getenv("LOCAL_LLM_URL", "http://127.0.0.1:11434/v1").strip()

# 3. Model Architecture (VALID model IDs only)
# Groq tool-calling models (from Groq's current model list). Override in .env if needed.
PRIMARY_MODEL: str = os.getenv("BERU_MODEL", "openai/gpt-oss-120b")
GROQ_BACKUP_MODEL: str = os.getenv("BERU_GROQ_BACKUP_MODEL", "openai/gpt-oss-20b")
GEMINI_MODEL: str = os.getenv("BERU_GEMINI_MODEL", "gemini-2.5-flash")
OPENROUTER_MODEL: str = os.getenv("BERU_OPENROUTER_MODEL", "openai/gpt-4o-mini")
# Local server model name (Ollama e.g. "llama3.2"). Empty = auto-detect the first installed model.
LOCAL_LLM_MODEL: str = os.getenv("BERU_LOCAL_MODEL", "").strip()

# 4. Cognitive, Performance & Safety Parameters
# Reduced from 15 to 8 for fast completion
MAX_TOOL_ROUNDS: int = int(os.getenv("BERU_MAX_ROUNDS", "8"))
TOOL_RESULT_CAP: int = int(os.getenv("BERU_TOOL_RESULT_CAP", "8000"))
TOOL_COMPRESS_THRESHOLD: int = int(os.getenv("BERU_TOOL_COMPRESS_THRESHOLD", "2000"))
CACHE_TTL_SECONDS: int = int(os.getenv("BERU_CACHE_TTL", "60"))
HEALTH_CACHE_TTL: int = int(os.getenv("BERU_HEALTH_CACHE_TTL", "30"))

ENABLE_PLANNER: bool = os.getenv("BERU_PLANNER", "1").lower() in ("1", "true", "yes", "on")
ENABLE_CRITIC: bool = os.getenv("BERU_CRITIC", "1").lower() in ("1", "true", "yes", "on")
ENABLE_REFLECT: bool = os.getenv("BERU_REFLECT", "1").lower() in ("1", "true", "yes", "on")
AUTO_APPROVE_SAFE: bool = os.getenv("BERU_AUTO_APPROVE_SAFE", "1").lower() in ("1", "true", "yes", "on")
ENABLE_STREAMING: bool = os.getenv("BERU_STREAMING", "1").lower() in ("1", "true", "yes", "on")
SHORT_CIRCUIT_INTENTS: bool = os.getenv("BERU_SHORT_CIRCUIT", "1").lower() in ("1", "true", "yes", "on")

# 5. Directories
WORKSPACE_DIR: Path = BASE_DIR / "workspace"
FORGE_DIR: Path = BASE_DIR / "workspace" / "forged_tools"
TRACES_DIR: Path = BASE_DIR / "workspace" / "traces"
SNAPSHOTS_DIR: Path = BASE_DIR / "workspace" / "snapshots"
BENCHMARKS_DIR: Path = BASE_DIR / "workspace" / "benchmarks"
BRAIN_DB_PATH: Path = BASE_DIR / "workspace" / "beru_ai_agent_brain.db"
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
FORGE_DIR.mkdir(parents=True, exist_ok=True)
TRACES_DIR.mkdir(parents=True, exist_ok=True)
SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
BENCHMARKS_DIR.mkdir(parents=True, exist_ok=True)
