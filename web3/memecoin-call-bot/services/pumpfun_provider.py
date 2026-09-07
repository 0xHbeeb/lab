import asyncio
import json
import logging
import time
from collections import defaultdict, deque
from typing import Any, Deque, Optional

import websockets

logger = logging.getLogger("pumpfun-provider")


class PumpFunProvider:
    WS_URL = "wss://pumpportal.fun/api/data"

    def __init__(self, api_key: str = "", window_seconds: int = 900):
        self.api_key = api_key.strip()
        self.window_seconds = max(60, window_seconds)
        self.enabled = bool(self.api_key)
        self._ws = None
        self._task: Optional[asyncio.Task] = None
        self._stop = False
        self._subscriptions: set[str] = set()
        self._events: dict[str, Deque[dict]] = defaultdict(deque)
        self._lock = asyncio.Lock()
        self._connected = asyncio.Event()

    async def start(self) -> None:
        if not self.enabled:
            logger.warning("Pump.fun disabled (set PUMPPORTAL_API_KEY)")
            return
        self._stop = False
        if not self._task or self._task.done():
            self._task = asyncio.create_task(self._run(), name="pumpfun-ws")

    async def close(self) -> None:
        self._stop = True
        self._connected.clear()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def subscribe(self, ca: str) -> None:
        if not self.enabled:
            return
        ca = ca.strip().lower()
        async with self._lock:
            if ca in self._subscriptions:
                return
            self._subscriptions.add(ca)
        if self._ws is not None:
            await self._send({"method": "subscribeTokenTrade", "keys": [ca]})

    async def count_recent_buys(self, ca: str) -> int:
        target = ca.strip().lower()
        now = time.time()
        async with self._lock:
            q = self._events.get(target)
            if not q:
                return 0
            cutoff = now - self.window_seconds
            while q and q[0].get("timestamp", 0) < cutoff:
                q.popleft()
            return len(q)

    async def recent_callers(self, ca: str) -> list[dict]:
        target = ca.strip().lower()
        cutoff = time.time() - self.window_seconds
        async with self._lock:
            q = self._events.get(target)
            if not q:
                return []
            while q and q[0].get("timestamp", 0) < cutoff:
                q.popleft()
            grouped = {}
            for event in q:
                username = event.get("username")
                if username:
                    grouped.setdefault(username, event)
            return list(grouped.values())[:20]

    async def _run(self) -> None:
        backoff = 2
        while not self._stop:
            try:
                uri = f"{self.WS_URL}?api-key={self.api_key}"
                async with websockets.connect(uri, ping_interval=20, ping_timeout=20, max_size=2**20) as ws:
                    self._ws = ws
                    self._connected.set()
                    logger.info("Pump.fun websocket connected")
                    async with self._lock:
                        subs = list(self._subscriptions)
                    if subs:
                        await self._send({"method": "subscribeTokenTrade", "keys": subs})
                    backoff = 2
                    async for raw in ws:
                        if self._stop:
                            break
                        await self._handle_message(raw)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Pump.fun websocket error")
            finally:
                self._connected.clear()
                self._ws = None
            if not self._stop:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def _send(self, payload: dict[str, Any]) -> None:
        if self._ws is None:
            return
        try:
            await self._ws.send(json.dumps(payload, separators=(",", ":")))
        except Exception:
            logger.exception("Failed sending Pump.fun subscription")

    async def _handle_message(self, raw: Any) -> None:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="ignore")
        if not isinstance(raw, str):
            return
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return
        if not isinstance(data, dict):
            return

        mint = str(data.get("mint") or data.get("token") or data.get("tokenAddress") or "").strip().lower()
        if not mint:
            return

        tx_type = str(data.get("txType") or data.get("type") or data.get("action") or "").lower()
        if tx_type not in {"buy", "create+buy", "buy_v2"}:
            return

        signature = str(data.get("signature") or data.get("txSignature") or data.get("hash") or "")
        event_time = self._event_time(data)
        trader = str(data.get("traderPublicKey") or data.get("trader") or data.get("user") or "").strip()
        username = str(data.get("username") or data.get("userName") or data.get("handle") or "").strip().lstrip("@")
        display = username or (f"trader_{trader[-6:]}" if trader else "")
        async with self._lock:
            q = self._events[mint]
            marker = signature or f"{event_time}:{len(q)}"
            if signature and any(item.get("marker") == signature for item in q):
                return
            q.append({"timestamp": event_time, "marker": marker, "username": display})
            cutoff = time.time() - self.window_seconds
            while q and q[0].get("timestamp", 0) < cutoff:
                q.popleft()

    @staticmethod
    def _event_time(data: dict[str, Any]) -> float:
        for key in ("timestamp", "time", "createdAt", "created_at"):
            try:
                value = float(data.get(key))
                if value > 10_000_000_000:
                    value /= 1000
                return value
            except (TypeError, ValueError):
                continue
        return time.time()