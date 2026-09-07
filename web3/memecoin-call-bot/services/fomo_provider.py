import asyncio
import json
import logging
import os
import time
from collections import defaultdict, deque
from typing import Any, Deque, Optional

logger = logging.getLogger("fomo-provider")


class FomoProvider:
    WS_URL = "wss://prod-api.fomo.family/ws"
    SITE_URL = "https://fomo.family/"

    def __init__(self, window_seconds: int = 900):
        self.window_seconds = max(60, window_seconds)
        self.mode = os.getenv("FOMO_MODE", "browser").strip().lower()
        self.jwt = os.getenv("FOMO_JWT", "").strip()
        self.profile_dir = os.getenv("FOMO_PROFILE_DIR", "data/fomo-profile")
        self.headless = os.getenv("FOMO_HEADLESS", "false").strip().lower() == "true"
        self.enabled = self.mode in {"browser", "jwt"}

        self._task: Optional[asyncio.Task] = None
        self._stop = False
        self._events: dict[str, Deque[dict]] = defaultdict(deque)
        self._token_buy5m: dict[str, int] = {}
        self._lock = asyncio.Lock()
        self._browser = None
        self._context = None
        self._page = None
        self._desired_subscriptions: set[str] = set()
        self._subscription_lock = asyncio.Lock()
        self._token_fetch_interval = max(20, int(os.getenv("FOMO_TOKEN_FETCH_SECONDS", "30")))
        self._last_token_fetch: dict[tuple[str, int], float] = {}
        self._token_fetch_lock = asyncio.Lock()

    async def start(self) -> None:
        if not self.enabled:
            logger.info("FOMO disabled (set FOMO_MODE=browser or jwt)")
            return
        self._stop = False
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run(), name="fomo-feed")

    async def close(self) -> None:
        self._stop = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        await self._close_browser()

    async def count_recent_buys(self, ca: str, chain: str = "") -> int:
        target = ca.strip().lower()
        now = time.time()
        cutoff = now - self.window_seconds
        async with self._lock:
            if target in self._token_buy5m:
                return max(0, int(self._token_buy5m[target]))
            q = self._events.get(target)
            if not q:
                return 0
            while q and q[0].get("timestamp", 0) < cutoff:
                q.popleft()
            return len(q)

    async def recent_callers(self, ca: str, chain: str = "") -> list[dict]:
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

    async def ensure_token_subscription(self, ca: str, chain: str = "") -> bool:
        if not self.enabled or self.mode != "browser" or self._page is None:
            return False
        network_id = self._network_id(chain)
        if network_id is None:
            return False
        target = ca.strip().lower()
        if not target:
            return False
        key = f"{target}:{network_id}"
        async with self._subscription_lock:
            self._desired_subscriptions.add(key)
        return await self._send_token_subscription(target, network_id)

    async def _send_token_subscription(self, ca: str, network_id: int) -> bool:
        if self._page is None:
            return False
        key = f"{ca.lower()}:{network_id}"
        try:
            result = await self._page.evaluate(
                r"""async ({ca, networkId, key}) => {
                    const sockets = window.__fomo_sockets ? window.__fomo_sockets() : [];
                    const socket = sockets.find(ws => ws && ws.readyState === 1);
                    if (!socket) return {ok:false, reason:'no-open-websocket'};
                    const sent = window.__fomo_sent_frames || [];
                    let template = null;
                    for (let i = sent.length - 1; i >= 0; i--) {
                        const item = sent[i];
                        if (item && String(item.topicType || '').toLowerCase() === 'token_details' && item.topicId) {
                            template = JSON.parse(JSON.stringify(item));
                            break;
                        }
                    }
                    if (!template) return {ok:false, reason:'no-token-details-template'};
                    template.topicId = `${ca}:${networkId}`;
                    socket.send(JSON.stringify(template));
                    window.__fomo_manual_subscriptions = window.__fomo_manual_subscriptions || {};
                    window.__fomo_manual_subscriptions[key] = Date.now();
                    return {ok:true, frame:template};
                }""",
                {"ca": ca, "networkId": network_id, "key": key},
            )
            if isinstance(result, dict) and result.get("ok"):
                logger.info("FOMO token_details subscribed: %s", key)
                return True
            logger.debug("FOMO subscription pending: %s", key)
        except Exception:
            logger.debug("FOMO subscription failed: %s", key, exc_info=True)
        return False

    async def _resubscribe_all(self) -> None:
        async with self._subscription_lock:
            keys = list(self._desired_subscriptions)
        for key in keys:
            try:
                ca, network_raw = key.rsplit(":", 1)
                await self._send_token_subscription(ca, int(network_raw))
            except Exception:
                pass

    async def _run(self) -> None:
        if self.mode == "jwt":
            if not self.jwt:
                logger.warning("FOMO JWT missing")
                return
            await self._run_jwt_loop()
            return
        await self._run_browser_loop()

    async def _run_browser_loop(self) -> None:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("FOMO browser requires playwright. Install: pip install playwright")
            return

        async with async_playwright() as p:
            try:
                self._context = await p.chromium.launch_persistent_context(
                    self.profile_dir,
                    headless=self.headless,
                    viewport={"width": 1440, "height": 900},
                )
                pages = self._context.pages
                self._page = pages[0] if pages else await self._context.new_page()
                await self._page.add_init_script(r"""(() => {
                    if (window.__fomo_ws_hook_installed) return;
                    window.__fomo_ws_hook_installed = true;
                    window.__fomo_ws_instances = new Set();
                    window.__fomo_sent_frames = [];
                    const NativeWebSocket = window.WebSocket;
                    const WrappedWebSocket = new Proxy(NativeWebSocket, {
                        construct(target, args, newTarget) {
                            const ws = Reflect.construct(target, args, newTarget);
                            window.__fomo_ws_instances.add(ws);
                            ws.addEventListener('close', () => window.__fomo_ws_instances.delete(ws));
                            return ws;
                        }
                    });
                    window.WebSocket = WrappedWebSocket;
                    window.__fomo_sockets = () => Array.from(window.__fomo_ws_instances);
                    const originalSend = NativeWebSocket.prototype.send;
                    NativeWebSocket.prototype.send = function(data) {
                        try {
                            if (typeof data === 'string') {
                                const parsed = JSON.parse(data);
                                if (parsed && (parsed.topicType || parsed.topicId)) {
                                    window.__fomo_sent_frames.push(parsed);
                                    if (window.__fomo_sent_frames.length > 200) window.__fomo_sent_frames.shift();
                                }
                            }
                        } catch (_) {}
                        return originalSend.call(this, data);
                    };
                })();""")
                self._page.on("websocket", self._on_websocket)
                self._page.on("response", lambda response: asyncio.create_task(self._on_response(response)))
                await self._page.goto(self.SITE_URL, wait_until="domcontentloaded")
                logger.info("FOMO browser session opened")
                while not self._stop:
                    await asyncio.sleep(5)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("FOMO browser error")
            finally:
                await self._close_browser()

    async def _on_websocket(self, ws) -> None:
        try:
            url = ws.url or ""
            if "prod-api.fomo.family/ws" not in url:
                return
            logger.info("FOMO websocket observed")
            ws.on("framereceived", lambda payload: asyncio.create_task(self._handle_frame(payload)))
            asyncio.create_task(self._resubscribe_after_ws_ready())
        except Exception:
            logger.exception("Failed attaching FOMO websocket listener")

    async def _resubscribe_after_ws_ready(self) -> None:
        await asyncio.sleep(2.0)
        await self._resubscribe_all()

    async def _handle_frame(self, payload: Any) -> None:
        text = payload
        if isinstance(payload, bytes):
            text = payload.decode("utf-8", errors="ignore")
        if not isinstance(text, str) or not text.strip():
            return
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return

        if isinstance(data, dict) and str(data.get("topicType", "")).lower() == "token_details":
            topic_id = str(data.get("topicId") or "")
            token_id = topic_id.split(":", 1)[0].strip().lower()
            payload_data = data.get("payload")
            if token_id and isinstance(payload_data, dict):
                value = payload_data.get("buys5min")
                try:
                    async with self._lock:
                        self._token_buy5m[token_id] = max(0, int(float(value)))
                except (TypeError, ValueError):
                    pass

        for event in self._extract_events(data):
            await self._record_event(event)

    async def _on_response(self, response) -> None:
        try:
            url = response.url
            if "prod-api.fomo.family" not in url:
                return
            path = url.split("prod-api.fomo.family", 1)[-1]
            low = path.lower()
            if not any(term in low for term in ("/feed", "/activity", "/signal")):
                return
            if response.status != 200:
                return
            text = await response.text()
            if not text:
                return
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                return
            for event in self._extract_events(payload):
                await self._record_event(event)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass

    async def _run_jwt_loop(self) -> None:
        try:
            import websockets
        except ImportError:
            logger.error("FOMO JWT requires websockets")
            return
        backoff = 2
        while not self._stop:
            try:
                async with websockets.connect(
                    self.WS_URL,
                    additional_headers={"Authorization": f"Bearer {self.jwt}"},
                    ping_interval=20,
                    ping_timeout=20,
                    max_size=2**20,
                ) as ws:
                    logger.info("FOMO JWT websocket connected")
                    backoff = 2
                    async for raw in ws:
                        await self._handle_frame(raw)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("FOMO JWT websocket error")
            if not self._stop:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def _record_event(self, event: dict[str, Any]) -> bool:
        ca = self._first_str(event, "tokenAddress", "token_address", "contractAddress", "contract_address", "mint", "address")
        if not ca:
            return False
        action_raw = self._first_str(event, "action", "side", "txType", "type").lower()
        blob = " ".join(str(v).lower() for v in event.values() if isinstance(v, (str, int, float)))
        if "sell" in action_raw or "sell" in blob:
            return False
        if "buy" not in action_raw and "buy" not in blob and "entry" not in blob and "long" not in blob:
            return False
        ts = self._event_time(event)
        marker = self._first_str(event, "tradeId", "trade_id", "txHash", "tx_hash", "id") or f"{ca}:{ts}"
        username = self._first_str(event, "userHandle", "user_handle", "username", "displayName").lstrip("@")
        market_cap = self._float(event.get("marketCap") or event.get("market_cap"))
        async with self._lock:
            q = self._events[ca.lower()]
            cutoff = time.time() - self.window_seconds
            while q and q[0].get("timestamp", 0) < cutoff:
                q.popleft()
            if any(existing.get("marker") == marker for existing in q):
                return False
            q.append({"timestamp": ts, "marker": marker, "username": username, "market_cap": market_cap})
        return True

    def _extract_events(self, obj: Any) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        seen: set[int] = set()

        def visit(value: Any):
            if isinstance(value, dict):
                oid = id(value)
                if oid in seen:
                    return
                seen.add(oid)
                if "tokenAddress" in value or "trading_activity" in str(value).lower():
                    out.append(value)
                for v in value.values():
                    visit(v)
            elif isinstance(value, list):
                for item in value:
                    visit(item)

        visit(obj)
        return out

    async def _close_browser(self) -> None:
        if self._context:
            await self._context.close()
            self._context = None
            self._page = None

    @staticmethod
    def _network_id(chain: str) -> Optional[int]:
        normalized = (chain or "").strip().lower().replace(" ", "")
        mapping = {"robinhood": 4663, "sol": 1399811149, "solana": 1399811149}
        return mapping.get(normalized)

    @staticmethod
    def _first_str(obj: dict, *keys) -> str:
        for key in keys:
            value = obj.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _event_time(data: dict) -> float:
        for key in ("timestamp", "time", "createdAt", "created_at"):
            try:
                value = float(data.get(key))
                if value > 10_000_000_000:
                    value /= 1000
                return value
            except (TypeError, ValueError):
                continue
        return time.time()

    @staticmethod
    def _float(value: Any) -> Optional[float]:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None