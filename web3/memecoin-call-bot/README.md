# Memecoin Call Bot — GitHub Starter

Clean starter extracted from the working local project. It keeps the current Python source and provider modules, but removes local runtime state (database, browser profile, caches, and Python bytecode) so it is suitable for adding to GitHub.

## Current modules

- Discord Call Panel / STOP CALL flow
- GMGN client integration
- Pump.fun provider integration
- FOMO browser/WebSocket integration
- Smart Wallet scoring engine
- Discord webhook sender/editor/deleter
- SQLite persistence layer

## Local setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
npm install -g gmgn-cli
copy .env.example .env
python bot.py
```

Fill `.env` with real credentials before running. Never commit `.env`, API keys, tokens, cookies, JWTs, browser profiles, or local databases.

## Remaining wiring / effort

This is intentionally a **starter**, not a claim that every requested production feature is fully finished.

Before calling it production-ready, review and wire together:

1. Final Discord webhook alert renderer and lifecycle.
2. Provider caller identity extraction and historical pre-call Smart Wallet lookup.
3. Final reference-matched Discord UI.
4. Provider-specific link generation and applicability rules.
5. Full integration tests for multiple simultaneous signals, replacement messages, STOP CALL, and reconnects.

## Environment

Copy `.env.example` to `.env` and fill the values locally.
