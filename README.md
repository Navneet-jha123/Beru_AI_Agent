# BERU AI Agent

BERU is a local-first, multi-mode assistant for research, business data work,
software development, automation, and specialized analysis. It has a Streamlit
web interface and an interactive command-line interface. Tools are selected
per request from a registry of functions so the model receives a relevant,
bounded set instead of the entire catalog.

## Run it

1. Use Python 3.10 or newer and install the dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and configure at least one model provider.
   Keep real credentials in `.env`; do not commit that file.
3. Start the web app with `streamlit run app.py`, or use `python main.py` for
   the CLI.

The Medical, Reverse Engineering, Data Analyst, and API modes require a model
endpoint on the same machine and fail closed if it is unavailable. Configure
`LOCAL_LLM_URL` for an installed local model server. The API mode additionally
requires reviewed hostnames in `BERU_API_ALLOWED_HOSTS`.

## Deploying for other people (bring your own keys)

When BERU is hosted for other users, each visitor pastes their own keys in the
app (Groq, Gemini, OpenRouter, Alpha Vantage, VirusTotal, Telegram) and only
those are used for their requests.

- Keys live in that browser session's server-side memory only. They are never
  written to disk or logs, and they are forgotten when the session ends or the
  visitor removes them.
- While a visitor's request runs, the server's own copies of these keys are
  hidden, so a leftover `.env` can never be used on someone's behalf.
- **Do not deploy a `.env` file or set these variables on the host.** Requests
  from different visitors run one at a time inside a process so keys can never
  mix; for many simultaneous users, run several instances behind a load
  balancer.
- Telegram alerts use a single bot per server process; per-visitor keys apply
  only to actions started from that visitor's session.
- Before deploying run `python api_keys.py --check` and `python -m pytest
  test_api_keys.py -q`. The check lists every place a key is read and flags any
  client created at import time (it would keep the server's key and must move
  inside a function).
- Running `python main.py` (CLI) still reads `.env` as before.

## Modes and business use

| Mode | Example work |
| --- | --- |
| General | Desktop assistance, browser research, memory, and project workflows |
| Developer | Code changes, command execution, builds, and guarded tool creation |
| Tester | Security review, test generation, fuzzing, and dependency checks |
| Hacker | Authorized passive security research and posture checks |
| Medical | Local calculators and bounded lab-value extraction; not diagnosis |
| Reverse Engineering | Bounded static file analysis; samples are not executed |
| Sports | Local sports calculations and configured score/standings providers |
| Data Analyst | Local CSV, TSV, SQLite, and Excel exploration |
| API | Reviewed OpenAPI operations on explicitly allowlisted hosts |

Business data workflows can start with `profile_csv` to see missing values,
summary statistics, common categories, and potential IQR outliers, then use
read-only SQL queries for follow-up questions. These are descriptive checks,
not forecasts or proof that a value is wrong. The API connector can bridge
approved services; writes are disabled unless explicitly enabled in config.
For a CRM or ERP, BERU can use its OpenAPI 3 specification and an exact host
allowlist. API-key or bearer values must come from environment variables.
Vendor-specific OAuth sign-in and per-tenant access management are not
implemented yet.

## Feedback, learning, and monitoring

- Each assistant answer can receive a helpful/not-helpful rating and a reason
  category. Feedback stays in `workspace/beru_feedback.db`; it stores a hash
  and character count for the answer, not the prompt or response text.
- Users can explicitly choose a fixed response-style preference (concise,
  detailed, bullets, or plain language). BERU applies it in non-private modes.
  Medical, Reverse Engineering, Data Analyst, API, and Watchdog modes do not
  read or update this preference.
- This is a controlled preference and evaluation loop, not model fine-tuning.
  Ratings are review signals and do not automatically change model weights,
  tools, or safety rules.
- Activity history shows a cached system-health snapshot, cumulative tool
  success/failure counts, and metadata-only model, tool, and session timings.
  The health snapshot refreshes when the page reruns and is cached for up to
  30 seconds; this is not a continuous alerting or auto-remediation service.

## Privacy and operational controls

- Private analysis modes expose a restricted tool allowlist and use a local
  model endpoint. Keep a local model server bound to loopback unless you have
  deliberately reviewed your network setup.
- Data analysis only reads files inside the project or its `workspace` folder;
  CSV and SQLite query results are capped. Excel formulas are not evaluated.
- OpenAPI calls use exact host allowlists. HTTPS and GET-only behavior are the
  defaults. Never put credentials directly in tool arguments or source files.
- Tool creation requires approval and runs in a subprocess with a stripped
  environment and timeout. Review any generated code before activation.
- Scheduling, file monitoring, system administration, browser automation, and
  other actions can affect the local machine. Review each tool's purpose and
  configuration before enabling it for unattended use.

## Product priorities

For a business-ready release, the highest-value next steps are to pick one
customer segment and ship a measurable workflow for it; add consented,
versioned evaluations for that workflow; and provide deployment, access,
retention, audit, and OAuth/tenant controls expected by that segment. Start with an outcome
such as time saved per report or fewer support handoffs, and validate it with
pilot users before pricing the product. Do not market current descriptive
analytics as predictive intelligence or current integrations as universal ERP
connectivity.

## Verification

Run the existing security suite with `python -m pytest test_security.py -q`.
Check the tool/schema registry with:

```powershell
python -c "from tools_registry import validate_registry_parity; print(validate_registry_parity())"
```

Optional capabilities such as market data, Telegram, screen detection, and
specialized file parsers require their documented provider credentials or
dependencies. Check `.env.example` and the feature-specific tool response for
the exact requirements.
