# Hermes + 9Router + Claude Sonnet 4.5 (Primary Only)

Simplified Windows setup for the configuration tested successfully with Hermes Agent, 9Router, Kiro OAuth, and Claude Sonnet 4.5.

## Architecture

```text
Hermes
  -> 9Router (http://localhost:20128/v1)
  -> Kiro OAuth
  -> kr/claude-sonnet-4.5
```

There is **no fallback provider** configured by this setup.

Existing providers in Hermes are preserved. This script does not delete or replace Xkiro.

## Requirements

- Hermes Agent installed under `%LOCALAPPDATA%\hermes`
- Hermes virtual-environment Python available at:
  `%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe`
- 9Router installed and running on port `20128`
- A 9Router API key available as the environment variable:
  `HERMES_9ROUTER_API_KEY`
- Kiro OAuth connection already configured in 9Router

## Setup

Run from PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\Hermes_9Router_Claude_Sonnet_PrimaryOnly.ps1
```

The script:

1. Checks the Hermes installation.
2. Verifies that 9Router is listening on `localhost:20128`.
3. Ensures `HERMES_9ROUTER_API_KEY` is persisted to the Windows User environment.
4. Creates a timestamped backup of `config.yaml`.
5. Configures the named Hermes provider `9router` to use:
   - Base URL: `http://localhost:20128/v1`
   - Model: `kr/claude-sonnet-4.5`
   - API mode: `chat_completions`
6. Leaves existing providers untouched.
7. Does not configure a fallback.

## After setup

Open a **new PowerShell window** so User environment variables are loaded, then restart the Hermes gateway.

Verify with:

```powershell
hermes model
```

Expected active model:

```text
Provider: 9Router Claude Sonnet 4.5
Model:    kr/claude-sonnet-4.5
URL:      http://localhost:20128/v1
```

## Credentials and secrets

Do not commit secrets to GitHub.

Never commit:

- `.env`
- `HERMES_9ROUTER_API_KEY` values
- Discord/Telegram tokens
- WhatsApp session files
- Kiro/OAuth secrets
- wallet/private keys
- cookies or browser credentials

The setup script itself does not contain an API key.

## Upstream and licensing

This setup is intended as a configuration/helper script for a modified Hermes Agent installation.

Keep the upstream Hermes Agent license and attribution with any redistributed Hermes source code.

Do not present the repository as an official Hermes Agent or Nous Research repository unless you have permission to do so.

Review the licenses and terms of every third-party project/service you redistribute or integrate, including Hermes Agent, 9Router, and provider-specific services.
