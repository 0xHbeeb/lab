import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from services.fomo_provider import FomoProvider
from services.gmgn_client import GMGNClient, GMGNError
from services.pumpfun_provider import PumpFunProvider
from services.token_service import TokenService
from services.smart_wallet_engine import SmartWalletEngine

logger = logging.getLogger("social-engine")


@dataclass
class SocialSnapshot:
    gmgn_count: int = 0
    pump_count: int = 0
    fomo_count: int = 0
    gmgn_callers: list[dict] = field(default_factory=list)
    pump_callers: list[dict] = field(default_factory=list)
    fomo_callers: list[dict] = field(default_factory=list)
    whale_count: int = 0
    smart_count: int = 0
    whale_callers: list[dict] = field(default_factory=list)
    smart_callers: list[dict] = field(default_factory=list)
    gmgn_score: Optional[float] = None
    pump_score: Optional[float] = None
    fomo_score: Optional[float] = None
    market_cap: Optional[float] = None
    price: Optional[float] = None
    volume_24h: Optional[float] = None
    liquidity: Optional[float] = None
    website_url: Optional[str] = None
    twitter_url: Optional[str] = None
    telegram_url: Optional[str] = None
    chart_url: Optional[str] = None
    launchpad: Optional[str] = None
    image_url: Optional[str] = None
    chain: Optional[str] = None
    last_error: Optional[str] = None


class SocialEngine:
    GMGN_CALL_TYPES = (13, 19)

    def __init__(
        self,
        gmgn: GMGNClient,
        token_service: TokenService,
        window_seconds: int = 900,
        signal_cache_seconds: int = 30,
        pumpfun: Optional[PumpFunProvider] = None,
        fomo: Optional[FomoProvider] = None,
        smart_config: Optional[dict] = None,
    ):
        self.gmgn = gmgn
        self.token_service = token_service
        self.window_seconds = max(60, window_seconds)
        self.signal_cache_seconds = max(10, signal_cache_seconds)
        self.pumpfun = pumpfun or PumpFunProvider("", window_seconds)
        self.fomo = fomo or FomoProvider(window_seconds)
        self._signal_cache: dict[str, tuple[float, Any]] = {}
        self.smart_engine = SmartWalletEngine(smart_config or {})

    async def start(self):
        await self.gmgn.start()
        await self.pumpfun.start()
        await self.fomo.start()

    async def close(self):
        await self.pumpfun.close()
        await self.fomo.close()
        await self.gmgn.close()

    async def fetch(self, ca: str, chain: str) -> SocialSnapshot:
        snapshot = SocialSnapshot()
        errors: list[str] = []

        gmgn_chain = self.token_service.normalize_chain(chain)

        try:
            info = await self.token_service.refresh(ca, gmgn_chain)
            snapshot.market_cap = info.market_cap
            snapshot.price = info.price
            snapshot.volume_24h = info.volume_24h
            snapshot.liquidity = info.liquidity
            snapshot.website_url = info.website_url
            snapshot.twitter_url = info.twitter_url
            snapshot.telegram_url = info.telegram_url
            snapshot.chart_url = info.chart_url
            snapshot.launchpad = info.launchpad
            snapshot.image_url = info.image_url
            snapshot.chain = info.chain
        except GMGNError as exc:
            errors.append(f"GMGN token info: {exc}")

        if self.gmgn.enabled and gmgn_chain:
            try:
                raw_count, raw_callers = await self._count_gmgn_calls(gmgn_chain, ca)
                snapshot.gmgn_count = raw_count
                snapshot.gmgn_callers = self.smart_engine.enrich_callers(raw_callers, "GMGN")
                snapshot.gmgn_score = float(snapshot.gmgn_count)
            except GMGNError as exc:
                errors.append(f"GMGN signals: {exc}")

        if gmgn_chain == "sol":
            try:
                await self.pumpfun.subscribe(ca)
                snapshot.pump_count = await self.pumpfun.count_recent_buys(ca)
                raw_pump_callers = await self.pumpfun.recent_callers(ca)
                snapshot.pump_callers = self.smart_engine.enrich_callers(raw_pump_callers, "Pump.fun")
                snapshot.pump_score = float(snapshot.pump_count)
            except Exception as exc:
                errors.append(f"Pump.fun: {exc}")

        try:
            await self.fomo.ensure_token_subscription(ca, chain)
            snapshot.fomo_count = await self.fomo.count_recent_buys(ca, chain)
            raw_fomo_callers = await self.fomo.recent_callers(ca, chain)
            snapshot.fomo_callers = self.smart_engine.enrich_callers(raw_fomo_callers, "FOMO")
            snapshot.fomo_score = float(snapshot.fomo_count)
        except Exception as exc:
            errors.append(f"FOMO: {exc}")

        snapshot.last_error = "; ".join(errors) if errors else None
        return snapshot

    async def fetch_historical_smart_callers(self, ca: str, chain: str, call_timestamp: float, lookback_seconds: int) -> list[dict]:
        """Fetch smart wallet entries for the same token that occurred before call_timestamp."""
        if not self.smart_engine.enabled:
            return []
        gmgn_chain = self.token_service.normalize_chain(chain)
        if not self.gmgn.enabled or not gmgn_chain:
            return []

        start_time = call_timestamp - lookback_seconds
        end_time = call_timestamp
        raw_historical = []
        seen_ids = set()
        for signal_type in self.GMGN_CALL_TYPES:
            try:
                data = await self._get_historical_signal_feed(gmgn_chain, signal_type, start_time, end_time)
                _, found = self._extract_exact_ca_with_callers(data, ca, signal_type, seen_ids, wallet_type=None)
                raw_historical.extend(found)
            except Exception:
                logger.exception("Failed fetching historical signal feed for %s", ca)

        # Enrich with smart engine and filter
        enriched = self.smart_engine.enrich_callers(raw_historical, "GMGN")
        min_score = self.smart_engine.min_score
        filtered = [
            caller for caller in enriched
            if caller.get("smart_eligible") and caller.get("smart_score", 0) >= min_score
        ]
        # Sort by timestamp descending (most recent first)
        filtered.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return filtered

    async def _get_historical_signal_feed(self, chain: str, signal_type: int, start_time: float, end_time: float) -> Any:
        """Fetch signal feed with time range using gmgn-cli if supported."""
        # Attempt with --start-time and --end-time
        try:
            data = await self.gmgn.run([
                "market", "signal",
                "--chain", chain,
                "--signal-type", str(signal_type),
                "--start-time", str(int(start_time)),
                "--end-time", str(int(end_time)),
            ])
            return data
        except Exception:
            # Fallback: fetch recent and filter locally
            logger.debug("gmgn-cli time range not supported, falling back to recent feed with local filter")
            data = await self._get_signal_feed(chain, signal_type)
            return data

    async def _count_gmgn_calls(self, chain: str, ca: str) -> tuple[int, list[dict[str, Any]]]:
        total = 0
        callers: list[dict[str, Any]] = []
        seen: set[str] = set()
        for signal_type in self.GMGN_CALL_TYPES:
            data = await self._get_signal_feed(chain, signal_type)
            count, found = self._extract_exact_ca_with_callers(data, ca, signal_type, seen, cutoff_timestamp=int(time.time()) - self.window_seconds)
            total += count
            callers.extend(found)
        return total, callers[:20]

    async def _count_gmgn_calls_by_wallet_type(self, chain: str, ca: str, wallet_type: str) -> tuple[int, list[dict[str, Any]]]:
        total = 0
        callers: list[dict[str, Any]] = []
        seen: set[str] = set()
        for signal_type in self.GMGN_CALL_TYPES:
            data = await self._get_signal_feed(chain, signal_type)
            count, found = self._extract_exact_ca_with_callers(data, ca, signal_type, seen, wallet_type=wallet_type)
            total += count
            callers.extend(found)
        return total, callers[:20]

    async def _get_signal_feed(self, chain: str, signal_type: int) -> Any:
        now = time.monotonic()
        cache_key = f"{chain}:{signal_type}"
        cached = self._signal_cache.get(cache_key)
        if cached and now - cached[0] < self.signal_cache_seconds:
            return cached[1]
        data = await self.gmgn.run([
            "market", "signal", "--chain", chain, "--signal-type", str(signal_type)
        ])
        self._signal_cache[cache_key] = (now, data)
        return data

    def _extract_exact_ca_with_callers(self, data: Any, ca: str, expected_type: int, seen_ids: set[str], wallet_type: Optional[str] = None, cutoff_timestamp: Optional[int] = None) -> tuple[int, list[dict[str, Any]]]:
        target = ca.strip().lower()
        if cutoff_timestamp is None:
            cutoff_timestamp = int(time.time()) - self.window_seconds
        total = 0
        callers: list[dict[str, Any]] = []
        for event in self._extract_events(data):
            address = str(event.get("token_address") or event.get("address") or event.get("token") or "").strip().lower()
            if address != target or self._int(event.get("signal_type")) != expected_type:
                continue
            if wallet_type:
                evt_wallet = str(event.get("wallet_type") or event.get("category") or "").strip().lower()
                if evt_wallet != wallet_type.lower():
                    continue
            trigger_at = self._int(event.get("trigger_at"))
            if trigger_at is not None and trigger_at < cutoff_timestamp:
                continue
            event_id = str(event.get("id") or "")
            if event_id and event_id in seen_ids:
                continue
            if event_id:
                seen_ids.add(event_id)
            total += 1
            caller = self._caller_from_event(event, wallet_type=wallet_type)
            if caller:
                callers.append(caller)
        return total, callers

    @staticmethod
    def _caller_from_event(event: dict[str, Any]) -> Optional[dict[str, Any]]:
        def pick(obj: Any) -> Optional[str]:
            if not isinstance(obj, dict):
                return None
            for key in ("username", "user_name", "userName", "handle", "userHandle", "screen_name", "traderUsername"):
                value = obj.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip().lstrip("@")
            return None

        username = pick(event)
        if username:
            return {
                "username": username,
                "timestamp": SocialEngine._int(event.get("trigger_at")) or int(time.time()),
                "market_cap": SocialEngine._float(event.get("market_cap") or event.get("trigger_mc")),
            }
        for key in ("user", "caller", "trader", "account", "author", "data"):
            value = event.get(key)
            username = pick(value)
            if username:
                return {
                    "username": username,
                    "timestamp": SocialEngine._int(event.get("trigger_at")) or int(time.time()),
                    "market_cap": SocialEngine._float(event.get("market_cap") or event.get("trigger_mc")),
                }
        return None

    @staticmethod
    def _extract_events(data: Any) -> list[dict[str, Any]]:
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if not isinstance(data, dict):
            return []
        events: list[dict[str, Any]] = []
        stack = [data]
        while stack:
            obj = stack.pop()
            for key in ("signals", "items", "list"):
                value = obj.get(key)
                if isinstance(value, list):
                    events.extend(x for x in value if isinstance(x, dict))
                elif isinstance(value, dict):
                    stack.append(value)
            value = obj.get("data")
            if isinstance(value, list):
                events.extend(x for x in value if isinstance(x, dict))
            elif isinstance(value, dict):
                stack.append(value)
        unique: list[dict[str, Any]] = []
        seen: set[str] = set()
        for event in events:
            marker = str(event.get("id") or "")
            if marker and marker in seen:
                continue
            if marker:
                seen.add(marker)
            unique.append(event)
        return unique

    @staticmethod
    def _int(value: Any, default: Optional[int] = None) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _float(value: Any) -> Optional[float]:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None