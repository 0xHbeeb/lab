# Memecoin Call Bot

A Python-based Discord bot for monitoring memecoin signals and managing call alerts.

## Features

- Discord Call Panel / STOP CALL flow
- GMGN client integration
- Pump.fun provider integration
- FOMO browser/WebSocket integration
- Smart Wallet scoring engine
- Discord webhook sender/editor/deleter
- SQLite persistence layer

## Local Setup

Create a virtual environment and install the required dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
npm install -g gmgn-cli
```

Copy the environment template:

```powershell
copy .env.example .env
```

Fill `.env` with the required credentials, then run:

```powershell
python bot.py
```

## Environment

Copy `.env.example` to `.env` and fill in the required values locally.

Never commit:

- `.env`
- API keys
- Tokens
- Cookies
- JWTs
- Browser profiles
- Local databases

## Project Status

This repository is provided as a starter and does not claim that every requested production feature is fully finished.

Before considering it production-ready, the following areas should be reviewed and wired together:

1. Final Discord webhook alert renderer and lifecycle.
2. Provider caller identity extraction and historical pre-call Smart Wallet lookup.
3. Final reference-matched Discord UI.
4. Provider-specific link generation and applicability rules.
5. Full integration tests for multiple simultaneous signals, replacement messages, STOP CALL, and reconnects.