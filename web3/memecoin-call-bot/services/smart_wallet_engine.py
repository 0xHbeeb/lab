import time
import logging
from dataclasses import dataclass, field
from typing import Optional, Any
from collections import defaultdict

logger = logging.getLogger("smart-wallet-engine")

@dataclass
class WalletProfile:
    wallet: str
    provider: str
    score: float = 0.0
    tier: str = "Ignore"
    win_rate: Optional[float] = None
    realized_pnl: Optional[float] = None
    trade_count: int = 0
    active_days: int = 0
    entry_quality: float = 0.0
    consistency: float = 0.0
    reputation: float = 0.0
    reasons: list[str] = field(default_factory=list)
    penalties: list[str] = field(default_factory=list)
    missing_data: list[str] = field(default_factory=list)
    eligible: bool = False
    last_updated: float = field(default_factory=time.time)

@dataclass
class SmartWalletResult:
    wallet: str
    provider: str
    eligible: bool
    score: float
    tier: str
    win_rate: Optional[float]
    realized_pnl: Optional[float]
    trade_count: int
    entry_quality: float
    consistency: float
    reputation: float
    reasons: list[str]
    penalties: list[str]
    missing_data: list[str]
    current_token_quality: float = 0.0

class SmartWalletEngine:
    def __init__(self, config: dict):
        self.enabled = config.get("SMART_WALLET_ENABLED", True)
        self.min_score = config.get("SMART_WALLET_MIN_SCORE", 80)
        self.min_trades = config.get("SMART_WALLET_MIN_TRADES", 50)
        self.min_active_days = config.get("SMART_WALLET_MIN_ACTIVE_DAYS", 30)
        self.min_realized_pnl = config.get("SMART_WALLET_MIN_REALIZED_PNL", 5000)
        self.min_win_rate = config.get("SMART_WALLET_MIN_WIN_RATE", 0.55)
        self.elite_score = config.get("SMART_WALLET_ELITE_SCORE", 90)
        self.cache_minutes = config.get("SMART_WALLET_CACHE_MINUTES", 30)
        self._cache: dict[str, WalletProfile] = {}
        self._cache_ttl = self.cache_minutes * 60

    def _is_cached_valid(self, wallet: str) -> bool:
        if wallet not in self._cache:
            return False
        return time.time() - self._cache[wallet].last_updated < self._cache_ttl

    def _get_cached(self, wallet: str) -> Optional[WalletProfile]:
        if self._is_cached_valid(wallet):
            return self._cache[wallet]
        return None

    def _cache_profile(self, profile: WalletProfile):
        profile.last_updated = time.time()
        self._cache[profile.wallet] = profile

    def _calculate_score(self, profile: WalletProfile) -> tuple[float, list[str], list[str]]:
        reasons = []
        penalties = []

        # 1. Historical Win Rate (30%)
        win_score = 0.0
        if profile.win_rate is not None and profile.trade_count >= self.min_trades:
            win_score = min(100, max(0, (profile.win_rate - 0.40) * 200))
            win_score = min(100, win_score * 1.2)
            reasons.append(f"WR {profile.win_rate:.1%} ({win_score:.0f})")
        else:
            profile.missing_data.append("win_rate or trade_count")

        # 2. Realized PnL (25%)
        pnl_score = 0.0
        if profile.realized_pnl is not None and profile.realized_pnl >= self.min_realized_pnl:
            if profile.realized_pnl >= 100_000:
                pnl_score = 95
            elif profile.realized_pnl >= 50_000:
                pnl_score = 80 + (profile.realized_pnl - 50_000) / 50_000 * 15
            elif profile.realized_pnl >= 10_000:
                pnl_score = 60 + (profile.realized_pnl - 10_000) / 40_000 * 20
            elif profile.realized_pnl >= 5_000:
                pnl_score = 40 + (profile.realized_pnl - 5_000) / 5_000 * 20
            pnl_score = min(100, max(0, pnl_score))
            reasons.append(f"PnL ${profile.realized_pnl:,.0f} ({pnl_score:.0f})")
        else:
            profile.missing_data.append("realized_pnl")

        # 3. Entry Quality (20%)
        entry_score = min(100, profile.entry_quality * 100)
        if entry_score > 50:
            reasons.append(f"Entry quality {entry_score:.0f}")
        else:
            profile.missing_data.append("entry_quality")

        # 4. Consistency (15%)
        consistency_score = min(100, profile.consistency * 100)
        if consistency_score > 50:
            reasons.append(f"Consistency {consistency_score:.0f}")
        else:
            profile.missing_data.append("consistency")

        # 5. Reputation (10%)
        rep_score = min(100, profile.reputation * 100)
        if rep_score > 50:
            reasons.append(f"Reputation {rep_score:.0f}")
        else:
            profile.missing_data.append("reputation")

        # Apply penalties
        for penalty in profile.penalties:
            if "wash" in penalty.lower():
                penalties.append("Wash trading penalty")
            elif "sniper" in penalty.lower():
                penalties.append("Sniper-only penalty")
            elif "bundle" in penalty.lower():
                penalties.append("Bundle-heavy penalty")
            elif "rug" in penalty.lower():
                penalties.append("Rug exposure penalty")
            elif "drawdown" in penalty.lower():
                penalties.append("Drawdown penalty")
            elif "one-hit" in penalty.lower():
                penalties.append("One-hit wonder penalty")

        raw_score = (
            win_score * 0.30 +
            pnl_score * 0.25 +
            entry_score * 0.20 +
            consistency_score * 0.15 +
            rep_score * 0.10
        )
        final_score = max(0, raw_score - len(penalties) * 10)
        return final_score, reasons, penalties

    def evaluate(self, wallet: str, provider: str, data: dict) -> SmartWalletResult:
        if not self.enabled:
            return self._fallback_result(wallet, provider, "Smart Wallet Engine disabled")

        cached = self._get_cached(wallet)
        if cached:
            profile = cached
        else:
            profile = self._build_profile(wallet, provider, data)
            self._cache_profile(profile)

        if not profile.eligible:
            return SmartWalletResult(
                wallet=wallet,
                provider=provider,
                eligible=False,
                score=0.0,
                tier="Not Eligible",
                win_rate=profile.win_rate,
                realized_pnl=profile.realized_pnl,
                trade_count=profile.trade_count,
                entry_quality=profile.entry_quality,
                consistency=profile.consistency,
                reputation=profile.reputation,
                reasons=["Insufficient data or does not meet minimum requirements"],
                penalties=profile.penalties,
                missing_data=profile.missing_data,
            )

        score, reasons, penalties = self._calculate_score(profile)

        if score >= self.elite_score:
            tier = "Elite Smart Wallet"
        elif score >= self.min_score:
            tier = "Smart Wallet"
        elif score >= 70:
            tier = "Good Trader"
        else:
            tier = "Ignore"

        return SmartWalletResult(
            wallet=wallet,
            provider=provider,
            eligible=True,
            score=round(score, 1),
            tier=tier,
            win_rate=profile.win_rate,
            realized_pnl=profile.realized_pnl,
            trade_count=profile.trade_count,
            entry_quality=profile.entry_quality,
            consistency=profile.consistency,
            reputation=profile.reputation,
            reasons=reasons,
            penalties=penalties,
            missing_data=profile.missing_data,
            current_token_quality=data.get("current_token_quality", 0.0),
        )

    def _build_profile(self, wallet: str, provider: str, data: dict) -> WalletProfile:
        win_rate = data.get("win_rate")
        realized_pnl = data.get("realized_pnl")
        trade_count = data.get("trade_count", 0)
        active_days = data.get("active_days", 0)
        entry_quality = data.get("entry_quality", 0.0)
        consistency = data.get("consistency", 0.0)
        reputation = data.get("reputation", 0.0)
        penalties = data.get("penalties", [])

        eligible = (
            trade_count >= self.min_trades and
            active_days >= self.min_active_days and
            realized_pnl is not None and realized_pnl >= self.min_realized_pnl and
            win_rate is not None and win_rate >= self.min_win_rate
        )

        return WalletProfile(
            wallet=wallet,
            provider=provider,
            win_rate=win_rate,
            realized_pnl=realized_pnl,
            trade_count=trade_count,
            active_days=active_days,
            entry_quality=entry_quality,
            consistency=consistency,
            reputation=reputation,
            eligible=eligible,
            penalties=penalties,
        )

    def _fallback_result(self, wallet: str, provider: str, reason: str) -> SmartWalletResult:
        return SmartWalletResult(
            wallet=wallet,
            provider=provider,
            eligible=False,
            score=0.0,
            tier="Disabled",
            win_rate=None,
            realized_pnl=None,
            trade_count=0,
            entry_quality=0.0,
            consistency=0.0,
            reputation=0.0,
            reasons=[reason],
            penalties=[],
            missing_data=[],
        )

    def enrich_callers(self, callers: list[dict], provider: str) -> list[dict]:
        if not self.enabled:
            return callers

        enriched = []
        for caller in callers:
            wallet = caller.get("wallet") or caller.get("address") or caller.get("user_id")
            if not wallet:
                enriched.append(caller)
                continue

            data = {
                "win_rate": caller.get("win_rate"),
                "realized_pnl": caller.get("realized_pnl"),
                "trade_count": caller.get("trade_count", 0),
                "active_days": caller.get("active_days", 0),
                "entry_quality": caller.get("entry_quality", 0.0),
                "consistency": caller.get("consistency", 0.0),
                "reputation": caller.get("reputation", 0.0),
                "penalties": caller.get("penalties", []),
                "current_token_quality": caller.get("current_token_quality", 0.0),
            }

            result = self.evaluate(wallet, provider, data)
            caller["smart_score"] = result.score
            caller["smart_tier"] = result.tier
            caller["smart_eligible"] = result.eligible
            caller["smart_reasons"] = result.reasons
            caller["smart_penalties"] = result.penalties
            caller["smart_win_rate"] = result.win_rate
            caller["smart_pnl"] = result.realized_pnl
            caller["smart_trade_count"] = result.trade_count
            caller["smart_entry_quality"] = result.entry_quality
            caller["smart_consistency"] = result.consistency
            caller["smart_reputation"] = result.reputation
            caller["smart_missing_data"] = result.missing_data
            enriched.append(caller)

        # Sort by score descending (Elite first), then by timestamp
        enriched.sort(key=lambda x: (x.get("smart_score", 0), x.get("timestamp", 0)), reverse=True)
        return enriched