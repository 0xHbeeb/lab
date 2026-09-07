import asyncio
import json
import logging
import os
import shutil
import subprocess
from typing import Any, Optional

logger = logging.getLogger("gmgn-client")


class GMGNError(RuntimeError):
    pass


class GMGNRateLimit(GMGNError):
    pass


class GMGNClient:
    """Async wrapper around gmgn-cli (official CLI)."""

    def __init__(self, api_key: str, timeout_seconds: int = 20):
        self.api_key = (api_key or "").strip()
        self.timeout_seconds = max(5, timeout_seconds)
        self._executable = self._find_executable()
        self._lock = asyncio.Lock()

    @staticmethod
    def _find_executable() -> Optional[str]:
        for name in ("gmgn-cli.cmd", "gmgn-cli", "gmgn-cli.exe"):
            found = shutil.which(name)
            if found:
                return found
        return None

    @property
    def enabled(self) -> bool:
        return bool(self.api_key) and bool(self._executable)

    @property
    def executable(self) -> Optional[str]:
        return self._executable

    async def start(self):
        if self.api_key:
            os.environ.setdefault("GMGN_API_KEY", self.api_key)
        if not self._executable:
            self._executable = self._find_executable()
        if not self._executable:
            raise GMGNError("gmgn-cli not in PATH. Run: npm install -g gmgn-cli")

    async def close(self):
        pass

    async def run(self, args: list[str]) -> Any:
        await self.start()
        assert self._executable is not None
        command = [self._executable, *args, "--raw"]

        env = os.environ.copy()
        if self.api_key:
            env["GMGN_API_KEY"] = self.api_key

        async with self._lock:
            try:
                if self._executable.lower().endswith((".cmd", ".bat")):
                    cmdline = subprocess.list2cmdline(command)
                    proc = await asyncio.create_subprocess_exec(
                        "cmd.exe", "/d", "/s", "/c", cmdline,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        env=env,
                    )
                else:
                    proc = await asyncio.create_subprocess_exec(
                        *command,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        env=env,
                    )
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=self.timeout_seconds
                )
            except asyncio.TimeoutError as exc:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass
                raise GMGNError("gmgn-cli timed out") from exc
            except OSError as exc:
                raise GMGNError(f"Unable to run gmgn-cli: {exc}") from exc

        out = stdout.decode("utf-8", errors="replace").strip()
        err = stderr.decode("utf-8", errors="replace").strip()

        if proc.returncode != 0:
            message = err or out or f"gmgn-cli exited {proc.returncode}"
            if "429" in message or "RATE_LIMIT" in message.upper():
                raise GMGNRateLimit(message)
            raise GMGNError(message)

        if not out:
            raise GMGNError("gmgn-cli returned empty output")

        try:
            return json.loads(out)
        except json.JSONDecodeError:
            starts = [i for i in (out.find("{"), out.find("[")) if i >= 0]
            if not starts:
                raise GMGNError(f"Non-JSON output: {out[:300]}")
            candidate = out[min(starts):]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError as exc:
                raise GMGNError(f"Invalid JSON: {out[:300]}") from exc

    async def token_info(self, chain: str, address: str) -> dict[str, Any]:
        result = await self.run(["token", "info", "--chain", chain, "--address", address])
        if isinstance(result, dict):
            return result
        if isinstance(result, list) and result and isinstance(result[0], dict):
            return result[0]
        raise GMGNError("Unexpected token info response")

    async def market_search(self, query: str) -> Any:
        return await self.run(["market", "search", "--query", query])