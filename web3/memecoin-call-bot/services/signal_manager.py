import asyncio
import logging
import os
import time
from collections import defaultdict
from typing import Optional

import discord

from database import Database, Signal
from services.social_engine import SocialEngine, SocialSnapshot
from services.token_service import TokenService
from services.discord_webhook import WebhookManager, DiscordWebhookError

logger = logging.getLogger("signal-manager")


class SignalManager:
    def __init__(
        self,
        bot: discord.Client,
        db: Database,
        token_service: TokenService,
        gmgn_client,
        refresh_seconds: int = 30,
        pumpfun_provider=None,
        fomo_provider=None,
        webhook_url: Optional[str] = None,
    ):
        self.bot = bot
        self.db = db
        self.token_service = token_service
        self.refresh_seconds = max(10, refresh_seconds)
        self.social_engine = SocialEngine(
            gmgn=gmgn_client,
            token_service=token_service,
            window_seconds=int(os.getenv("SOCIAL_WINDOW_SECONDS", "900")),
            signal_cache_seconds=int(os.getenv("SOCIAL_SIGNAL_CACHE_SECONDS", "30")),
            pumpfun=pumpfun_provider,
            fomo=fomo_provider,
        )
        self.webhook = WebhookManager(webhook_url) if webhook_url else None
        self._task: Optional[asyncio.Task] = None
        self._refresh_task: Optional[asyncio.Task] = None
        self._stopping = False
        self._locks = defaultdict(asyncio.Lock)
        self._dirty_signals: set[str] = set()
        self._dirty_lock = asyncio.Lock()
        self._flush_interval = max(5, refresh_seconds // 3)  # Update every few seconds

    async def start(self):
        self._stopping = False
        await self.social_engine.start()
        self._task = asyncio.create_task(self._refresh_loop())
        if self.webhook:
            self._refresh_task = asyncio.create_task(self._flush_loop())

    async def stop(self):
        self._stopping = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._refresh_task:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass
        await self.social_engine.close()
        if self.webhook:
            await self.webhook.close()

    async def create_or_add_call(self, guild: discord.Guild, user: discord.Member, ca: str, alert_channel_id: int) -> tuple[Signal, bool]:
        async with self._locks[ca]:
            existing = self.db.get_signal(ca)
            if existing:
                existing_was_active = existing.status == "ACTIVE"
                if not any(int(c["user_id"]) == user.id for c in existing.callers):
                    existing.callers.append({"user_id": user.id, "username": user.display_name})
                existing.status = "ACTIVE" if existing.status != "ACTIVE" else existing.status
                self.db.update_signal(existing)
                # New Discord caller: replace the webhook message (delete + send new)
                await self._replace_for_new_caller(existing)
                return existing, False

            info = await self.token_service.resolve(ca)
            now_ts = time.time()
            signal = Signal(
                ca=ca,
                symbol=info.symbol,
                name=info.name,
                chain=info.chain,
                creator_id=user.id,
                callers=[{"user_id": user.id, "username": user.display_name}],
                alert_channel_id=alert_channel_id,
                market_cap=info.market_cap,
                price=info.price,
                volume_24h=info.volume_24h,
                liquidity=info.liquidity,
                website_url=info.website_url,
                twitter_url=info.twitter_url,
                telegram_url=info.telegram_url,
                chart_url=info.chart_url,
                launchpad=info.launchpad,
                image_url=info.image_url,
                discord_call_timestamp=now_ts,
            )
            # Fetch historical smart wallet entries before the call
            lookback_hours = int(os.getenv("SMART_WALLET_LOOKBACK_HOURS", "24"))
            lookback_seconds = lookback_hours * 3600
            historical = await self.social_engine.fetch_historical_smart_callers(
                ca, info.chain, now_ts, lookback_seconds
            )
            signal._historical_smart_callers = historical
            self.db.insert_signal(signal)
            # Send initial webhook message
            await self._send_webhook_message(signal)
            return signal, True

    async def stop_call(self, guild: discord.Guild, user: discord.Member, ca: str) -> tuple[bool, str]:
        async with self._locks[ca]:
            signal = self.db.get_signal(ca)
            if not signal:
                return False, "No active or known call exists for that contract address."
            if signal.creator_id != user.id:
                return False, "Only the first person who called this memecoin can stop the call."
            if signal.status == "STOPPED":
                return False, "This memecoin call is already stopped."
            signal = self.db.stop_signal(ca)
            if not signal:
                return False, "Unable to stop the call."
            # Final edit to mark stopped
            await self._edit_webhook_message(signal)
            # Remove from dirty set
            async with self._dirty_lock:
                self._dirty_signals.discard(signal.ca)
            return True, "Call stopped. Live updates have been disabled."

    async def _send_webhook_message(self, signal: Signal):
        if not self.webhook:
            raise RuntimeError("Webhook not configured")
        embed = self._build_embed(signal)
        try:
            data = await self.webhook.send(embed)
            signal.message_id = int(data["id"])
            self.db.update_signal(signal)
            logger.info("Webhook message sent for %s, ID=%s", signal.ca, signal.message_id)
        except DiscordWebhookError as e:
            logger.exception("Failed to send webhook message for %s", signal.ca)
            raise

    async def _edit_webhook_message(self, signal: Signal):
        if not self.webhook:
            return
        if not signal.message_id:
            logger.warning("No message ID to edit for %s, sending new", signal.ca)
            await self._send_webhook_message(signal)
            return
        embed = self._build_embed(signal)
        try:
            ok = await self.webhook.edit(signal.message_id, embed)
            if not ok:
                # 404: message gone, re-send
                logger.warning("Webhook message %s gone, re-sending for %s", signal.message_id, signal.ca)
                await self._send_webhook_message(signal)
            else:
                logger.debug("Webhook message %s edited for %s", signal.message_id, signal.ca)
        except DiscordWebhookError as e:
            logger.exception("Failed to edit webhook message for %s", signal.ca)
            raise

    async def _replace_for_new_caller(self, signal: Signal):
        """Delete old webhook message and send a new one (for new Discord caller)."""
        if not self.webhook:
            raise RuntimeError("Webhook not configured")
        old_id = signal.message_id
        if old_id:
            try:
                await self.webhook.delete(old_id)
            except DiscordWebhookError as e:
                logger.exception("Failed to delete webhook message %s for new caller", old_id)
        # Send new message
        await self._send_webhook_message(signal)

    def _build_embed(self, signal: Signal) -> discord.Embed:
        """Build the vertical signal card with Called by @user1 · @user2 at top."""
        is_stopped = signal.status == "STOPPED"
        title_emoji = "🛑" if is_stopped else "🔥🔥🔥"
        embed = discord.Embed(
            title=f"{title_emoji} ${signal.symbol}",
            color=discord.Color.orange(),
        )
        if signal.image_url:
            try:
                embed.set_thumbnail(url=signal.image_url)
            except Exception:
                pass

        # Top: Called by Discord users
        caller_mentions = [f"<@{c['user_id']}>" for c in signal.callers[:10]]
        if len(signal.callers) > 10:
            caller_mentions.append(f"+{len(signal.callers)-10} more")
        lines: list[str] = [
            "Called by " + " · ".join(caller_mentions) if caller_mentions else "Called by nobody",
            "",
            "💰 **Market Cap**",
            self._money(signal.market_cap) if signal.market_cap is not None else "—",
            "",
            "⛓️ **Chain**",
            str(signal.chain or "—"),
            "",
            "📈 **Chart**",
            f"[GMGN]({signal.chart_url})" if signal.chart_url else "—",
        ]

        def caller_rows(users: list[dict]) -> list[str]:
            grouped: dict[str, dict] = {}
            order: list[str] = []
            # Sort by smart score descending if available (Elite first)
            sorted_users = sorted(users, key=lambda x: x.get("smart_score", 0), reverse=True)
            for item in sorted_users:
                uname = str(item.get("username") or "").strip().lstrip("@")
                if not uname:
                    continue
                key = uname.lower()
                if key not in grouped:
                    grouped[key] = {"username": uname, "count": 0, "market_cap": None, "timestamp": None, "smart_score": None, "smart_tier": None, "smart_pnl": None, "smart_win_rate": None}
                    order.append(key)
                grouped[key]["count"] += int(item.get("count") or 1)
                if item.get("market_cap") is not None:
                    grouped[key]["market_cap"] = item.get("market_cap")
                if item.get("timestamp") is not None:
                    grouped[key]["timestamp"] = item.get("timestamp")
                if item.get("smart_score") is not None:
                    grouped[key]["smart_score"] = max(grouped[key].get("smart_score") or 0, item["smart_score"])
                if item.get("smart_tier"):
                    grouped[key]["smart_tier"] = item.get("smart_tier")
                if item.get("smart_pnl") is not None:
                    grouped[key]["smart_pnl"] = item.get("smart_pnl")
                if item.get("smart_win_rate") is not None:
                    grouped[key]["smart_win_rate"] = item.get("smart_win_rate")
            rows: list[str] = []
            for key in order:
                item = grouped[key]
                prefix = ""
                tier = item.get("smart_tier")
                if tier and tier in ("Elite Smart Wallet", "Smart Wallet"):
                    if "Elite" in tier:
                        prefix = "👑 "
                    else:
                        prefix = "🧠 "
                extra = f" ×{item['count']}" if item["count"] > 1 else ""
                if item.get("market_cap") is not None:
                    extra += f" · {self._money(float(item['market_cap']))} MC"
                if item.get("timestamp"):
                    extra += self._format_ago(float(item["timestamp"]))
                smart_info = ""
                if item.get("smart_score") is not None and item.get("smart_score") >= 0:
                    smart_info = f" · Score {item['smart_score']:.0f}"
                    if item.get("smart_win_rate") is not None:
                        smart_info += f" · WR {item['smart_win_rate']:.1%}"
                    if item.get("smart_pnl") is not None and item["smart_pnl"] != 0:
                        smart_info += f" · ${item['smart_pnl']:,.0f} PnL"
                rows.append(f"{prefix}@{item['username']}{extra}{smart_info}")
            return rows

        def add_source(emoji: str, label: str, count: int, users: list[dict]):
            if count == 0 and not users:
                return
            lines.extend(["", f"{emoji} **Called out**", f"{label} ×{count}"])
            rows = caller_rows(users)
            if rows:
                show = rows[:3]
                lines.extend(show)
                remaining = max(0, len(rows) - len(show))
                if remaining:
                    lines.append(f"`+{remaining} more`")
            else:
                lines.append("—")

        def add_historical_smart(users: list[dict]):
            if not users:
                return
            lines.extend(["", "🧠 **Smart Wallet Entry**"])
            rows = caller_rows(users)
            if rows:
                # Show all historical smart wallets (they are already filtered)
                lines.extend(rows)
            else:
                lines.append("—")

        gmgn_users = getattr(signal, "_gmgn_callers", []) or []
        pump_users = getattr(signal, "_pump_callers", []) or []
        fomo_users = getattr(signal, "_fomo_callers", []) or []

        # Historical smart wallets
        historical_smart = getattr(signal, "_historical_smart_callers", []) or []
        add_historical_smart(historical_smart)

        add_source("📣", "GMGN", int(signal.gmgn_count or 0), gmgn_users)
        add_source("🚀", "Pump", int(signal.pump_count or 0), pump_users)
        add_source("😈", "FOMO", int(signal.fomo_count or 0), fomo_users)

        if signal.launchpad:
            lines.extend(["", "**Launchpad**", str(signal.launchpad)])

        lines.extend(["", "🔗 **Platforms**"])
        platform_links = []
        if signal.chart_url:
            platform_links.append(f"[GMGN]({signal.chart_url})")
        is_sol = str(signal.chain or "").lower() in {"solana", "sol"}
        if is_sol and signal.ca:
            platform_links.append(f"[Pump.fun](https://pump.fun/coin/{signal.ca})")
        if signal.ca:
            platform_links.append(f"[FOMO](https://fomo.family/t/{signal.ca})")
        if platform_links:
            lines.append(" • ".join(platform_links))
        else:
            lines.append("—")

        lines.extend(["", "🌐 **Social**"])
        social_links = []
        if signal.website_url:
            social_links.append(f"[Website]({signal.website_url})")
        if signal.twitter_url:
            social_links.append(f"[X]({signal.twitter_url})")
        if signal.telegram_url:
            social_links.append(f"[Telegram]({signal.telegram_url})")
        if social_links:
            lines.append(" • ".join(social_links))
        else:
            lines.append("—")

        lines.extend(["", "📋 **Contract**", f"`{signal.ca}`"])
        footer = "Live social updates paused" if is_stopped else "Live social engine active"
        if signal.last_error and not is_stopped:
            footer += " • provider error"

        embed.description = "\n".join(lines)
        embed.set_footer(text=footer)
        return embed

    @staticmethod
    def _format_ago(timestamp: float) -> str:
        import time
        seconds = max(0, int(time.time() - timestamp))
        if seconds < 60:
            return f" · {seconds}s ago"
        elif seconds < 3600:
            return f" · {seconds // 60}m ago"
        else:
            return f" · {seconds // 3600}h ago"

    @staticmethod
    def _money(value: float) -> str:
        if value >= 1_000_000_000:
            return f"${value / 1_000_000_000:.2f}B"
        if value >= 1_000_000:
            return f"${value / 1_000_000:.2f}M"
        if value >= 1_000:
            return f"${value / 1_000:.1f}K"
        return f"${value:.4f}"

    async def _refresh_loop(self):
        await self.bot.wait_until_ready()
        while not self._stopping:
            try:
                signals = self.db.get_active_signals()
                for signal in signals:
                    await self._refresh_one(signal)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Background refresh loop error")
            await asyncio.sleep(self.refresh_seconds)

    async def _flush_loop(self):
        await self.bot.wait_until_ready()
        while not self._stopping:
            try:
                async with self._dirty_lock:
                    dirty = list(self._dirty_signals)
                    self._dirty_signals.clear()
                for ca in dirty:
                    try:
                        signal = self.db.get_signal(ca)
                        if signal and signal.status == "ACTIVE":
                            async with self._locks[ca]:
                                # Re-fetch latest to ensure we have fresh data
                                signal = self.db.get_signal(ca)
                                if signal and signal.status == "ACTIVE":
                                    await self._edit_webhook_message(signal)
                    except Exception as e:
                        logger.exception("Failed to flush dirty signal %s", ca)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Flush loop error")
            await asyncio.sleep(self._flush_interval)

    async def _refresh_one(self, signal: Signal):
        async with self._locks[signal.ca]:
            latest = self.db.get_signal(signal.ca)
            if not latest or latest.status != "ACTIVE":
                return

            snapshot = await self.social_engine.fetch(latest.ca, latest.chain)
            changed = (
                latest.gmgn_count != snapshot.gmgn_count
                or latest.pump_count != snapshot.pump_count
                or latest.fomo_count != snapshot.fomo_count
                or latest.market_cap != snapshot.market_cap
                or latest.price != snapshot.price
                or latest.volume_24h != snapshot.volume_24h
                or latest.liquidity != snapshot.liquidity
                or latest.website_url != snapshot.website_url
                or latest.twitter_url != snapshot.twitter_url
                or latest.telegram_url != snapshot.telegram_url
                or latest.chart_url != snapshot.chart_url
                or latest.launchpad != snapshot.launchpad
                or getattr(latest, "image_url", None) != getattr(snapshot, "image_url", None)
                or latest.chain != snapshot.chain
                or latest.last_error != snapshot.last_error
            )
            self.db.update_social_metrics(latest.ca, snapshot.__dict__)
            latest._gmgn_callers = list(snapshot.gmgn_callers or [])
            latest._pump_callers = list(snapshot.pump_callers or [])
            latest._fomo_callers = list(snapshot.fomo_callers or [])
            # Preserve historical smart callers (already set at creation time)
            if changed and latest.status == "ACTIVE":
                # Mark dirty for flush loop
                async with self._dirty_lock:
                    self._dirty_signals.add(latest.ca)
                logger.debug("Signal %s marked dirty for webhook update", latest.ca)