import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

from services.gmgn_client import GMGNClient, GMGNError

logger = logging.getLogger("token-service")


@dataclass
class TokenInfo:
    ca: str
    symbol: str
    name: str
    chain: str
    market_cap: Optional[float] = None
    price: Optional[float] = None
    volume_24h: Optional[float] = None
    liquidity: Optional[float] = None
    chart_url: Optional[str] = None
    website_url: Optional[str] = None
    twitter_url: Optional[str] = None
    telegram_url: Optional[str] = None
    launchpad: Optional[str] = None
    image_url: Optional[str] = None


class TokenService:
    EVM_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
    SOL_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")

    DISPLAY_CHAIN = {
        "sol": "Solana",
        "bsc": "BSC",
        "base": "Base",
        "eth": "Ethereum",
        "robinhood": "Robinhood",
        "arc": "Arc",
        "stable": "Stable",
    }

    def __init__(self, gmgn: GMGNClient, default_evm_chain: str = "robinhood"):
        self.gmgn = gmgn
        aliases = {
            "solana": "sol",
            "ethereum": "eth",
            "bnb": "bsc",
            "binance smart chain": "bsc",
            "robinhood chain": "robinhood",
        }
        raw_default = (default_evm_chain or "robinhood").strip().lower()
        raw_default = aliases.get(raw_default, raw_default)
        self.default_evm_chain = raw_default if raw_default in self.DISPLAY_CHAIN else "robinhood"

    def validate_ca(self, ca: str) -> bool:
        ca = ca.strip()
        return bool(self.EVM_RE.fullmatch(ca) or self.SOL_RE.fullmatch(ca))

    async def resolve(self, ca: str) -> TokenInfo:
        ca = ca.strip()
        if not self.validate_ca(ca):
            raise ValueError("Invalid contract address format")
        if not self.gmgn.enabled:
            return TokenInfo(
                ca=ca,
                symbol="MEME",
                name="Memecoin",
                chain="Solana" if self.SOL_RE.fullmatch(ca) else self.DISPLAY_CHAIN.get(self.default_evm_chain, self.default_evm_chain.upper()),
            )

        try:
            result = await self.gmgn.market_search(ca)
            coin = self._find_exact_coin(result, ca)
            if coin:
                chain = self.normalize_chain(str(coin.get("chain") or ""))
                if chain:
                    return await self._resolve_chain(ca, chain, fallback=coin)
        except GMGNError:
            logger.exception("GMGN market search failed for %s", ca)

        chains = ["sol"] if self.SOL_RE.fullmatch(ca) else [
            self.default_evm_chain,
            *[c for c in ("robinhood", "base", "bsc", "eth", "arc", "stable") if c != self.default_evm_chain],
        ]
        last_error: Optional[Exception] = None
        for chain in chains:
            try:
                return await self._resolve_chain(ca, chain)
            except GMGNError as exc:
                last_error = exc
                continue

        if last_error:
            raise last_error
        raise GMGNError("Token could not be resolved")

    async def refresh(self, ca: str, chain: str, fallback: Optional[TokenInfo] = None) -> TokenInfo:
        gmgn_chain = self.normalize_chain(chain)
        if not self.gmgn.enabled or not gmgn_chain or gmgn_chain == "EVM":
            return fallback or TokenInfo(ca=ca, symbol="MEME", name="Memecoin", chain=chain)
        try:
            return await self._resolve_chain(ca, gmgn_chain, fallback=self._token_to_dict(fallback) if fallback else None)
        except GMGNError:
            if fallback:
                raise
            raise

    def normalize_chain(self, chain: str) -> str:
        raw = (chain or "").strip().lower()
        aliases = {
            "solana": "sol",
            "ethereum": "eth",
            "bnb": "bsc",
            "binance smart chain": "bsc",
            "robinhood chain": "robinhood",
        }
        if raw == "evm":
            return self.default_evm_chain
        return aliases.get(raw, raw)

    async def _resolve_chain(self, ca: str, chain: str, fallback: Optional[dict[str, Any]] = None) -> TokenInfo:
        data = fallback or {}
        if self.gmgn.enabled:
            token_data = await self.gmgn.token_info(chain, ca)
            if isinstance(token_data, dict):
                data = token_data
        return self._from_gmgn(ca, chain, data)

    def _from_gmgn(self, ca: str, chain: str, data: dict[str, Any]) -> TokenInfo:
        price_obj = data.get("price") or {}
        link = data.get("link") or {}
        price = self._float(price_obj.get("price"))
        supply = self._float(data.get("circulating_supply"))
        market_cap = self._float(data.get("market_cap"))
        if market_cap is None and price is not None and supply is not None:
            market_cap = price * supply

        volume_24h = self._float(price_obj.get("volume_24h"))
        symbol = str(data.get("symbol") or "MEME")
        name = str(data.get("name") or "Memecoin")
        website = link.get("website") or None
        twitter_user = link.get("twitter_username")
        twitter = f"https://x.com/{twitter_user}" if twitter_user else link.get("twitter")
        return TokenInfo(
            ca=ca,
            symbol=symbol,
            name=name,
            chain=self.DISPLAY_CHAIN.get(chain, chain.upper() if chain else "EVM"),
            market_cap=market_cap,
            price=price,
            volume_24h=volume_24h,
            liquidity=self._float(data.get("liquidity")),
            chart_url=link.get("gmgn") or f"https://gmgn.ai/{chain}/token/{ca}",
            website_url=website,
            twitter_url=twitter,
            telegram_url=link.get("telegram") or None,
            launchpad=data.get("launchpad_platform") or data.get("launchpad"),
            image_url=self._image_url(data),
        )

    @staticmethod
    def _find_exact_coin(result: Any, ca: str) -> Optional[dict[str, Any]]:
        target = ca.strip().lower()
        if not isinstance(result, dict):
            return None
        data = result.get("data")
        if isinstance(data, dict):
            coins = data.get("coins") or []
        else:
            coins = result.get("coins") or []
        if not isinstance(coins, list):
            return None
        for coin in coins:
            if not isinstance(coin, dict):
                continue
            address = str(coin.get("address") or "").strip().lower()
            if address == target:
                return coin
        return None

    @staticmethod
    def _image_url(data: dict[str, Any]) -> Optional[str]:
        candidates = [
            data.get("logo"),
            data.get("logo_url"),
            data.get("image"),
            data.get("image_url"),
            data.get("token_logo"),
            data.get("token_logo_url"),
        ]
        link = data.get("link") or {}
        if isinstance(link, dict):
            candidates.extend([
                link.get("logo"),
                link.get("logo_url"),
                link.get("image"),
                link.get("image_url"),
            ])
        for value in candidates:
            if isinstance(value, str) and value.strip().startswith(("http://", "https://")):
                return value.strip()
        return None

    @staticmethod
    def _float(value: Any) -> Optional[float]:
        try:
            return float(value) if value is not None and value != "" else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _token_to_dict(info: Optional["TokenInfo"]) -> dict[str, Any]:
        if not info:
            return {}
        return {
            "symbol": info.symbol,
            "name": info.name,
            "liquidity": info.liquidity,
            "price": {"price": info.price, "volume_24h": info.volume_24h},
            "market_cap": info.market_cap,
            "link": {
                "gmgn": info.chart_url,
                "website": info.website_url,
                "twitter": info.twitter_url,
                "telegram": info.telegram_url,
            },
            "launchpad_platform": info.launchpad,
        }