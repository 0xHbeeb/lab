import os
import logging

import discord
from discord.ext import commands
from dotenv import load_dotenv

from database import Database
from services.signal_manager import SignalManager
from services.token_service import TokenService
from services.gmgn_client import GMGNClient
from services.pumpfun_provider import PumpFunProvider
from services.fomo_provider import FomoProvider
from cogs.call_memecoin import CallMemecoinCog

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
DB_PATH = os.getenv("DB_PATH", "data/bot.db")
ALERT_REFRESH_SECONDS = int(os.getenv("ALERT_REFRESH_SECONDS", "30"))
GMGN_API_KEY = os.getenv("GMGN_API_KEY", "")
GMGN_BASE_URL = os.getenv("GMGN_BASE_URL", "https://openapi.gmgn.ai")
CALL_PANEL_CHANNEL_ID = int(os.getenv("CALL_PANEL_CHANNEL_ID", "0"))
MEMECOIN_ALERT_CHANNEL_ID = int(os.getenv("MEMECOIN_ALERT_CHANNEL_ID", "0"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("memecoin-bot")

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing from .env")
if not CALL_PANEL_CHANNEL_ID:
    raise RuntimeError("CALL_PANEL_CHANNEL_ID is missing from .env")
if not MEMECOIN_ALERT_CHANNEL_ID:
    raise RuntimeError("MEMECOIN_ALERT_CHANNEL_ID is missing from .env")

intents = discord.Intents.default()
intents.guilds = True
intents.members = True


class MemecoinBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents, help_command=None)
        self.logger = logger
        self.db = Database(DB_PATH)
        self.gmgn_client = GMGNClient(GMGN_API_KEY)
        self.token_service = TokenService(self.gmgn_client, default_evm_chain=os.getenv("DEFAULT_EVM_CHAIN", "robinhood"))
        self.pumpfun_provider = PumpFunProvider(
            os.getenv("PUMPPORTAL_API_KEY", ""),
            int(os.getenv("SOCIAL_WINDOW_SECONDS", "900")),
        )
        self.fomo_provider = FomoProvider(int(os.getenv("SOCIAL_WINDOW_SECONDS", "900")))
        self.signal_manager = SignalManager(
            bot=self,
            db=self.db,
            token_service=self.token_service,
            gmgn_client=self.gmgn_client,
            refresh_seconds=ALERT_REFRESH_SECONDS,
            pumpfun_provider=self.pumpfun_provider,
            fomo_provider=self.fomo_provider,
            webhook_url=os.getenv("DISCORD_WEBHOOK_URL"),
        )
        self.call_panel_posted = False

    async def setup_hook(self):
        await self.add_cog(CallMemecoinCog(self))
        await self.signal_manager.start()

    @property
    def call_panel_view(self):
        return self.get_cog("CallMemecoinCog").view

    async def on_ready(self):
        logger.info("Logged in as %s (%s)", self.user, self.user.id)
        if GMGN_API_KEY:
            logger.info("GMGN live engine: ENABLED")
        else:
            logger.warning("GMGN live engine: DISABLED (set GMGN_API_KEY in .env)")
        logger.info("Pump.fun live engine: %s", "ENABLED" if os.getenv("PUMPPORTAL_API_KEY") else "DISABLED")
        logger.info("FOMO live engine: %s", "ENABLED" if os.getenv("FOMO_MODE", "browser").strip().lower() in {"browser", "jwt"} else "DISABLED")

        try:
            synced = await self.tree.sync()
            logger.info("Synced %d global command(s)", len(synced))
        except Exception:
            logger.exception("Global command sync failed")

        if not self.call_panel_posted:
            await self.ensure_call_panel()
            self.call_panel_posted = True

    async def ensure_call_panel(self):
        channel = self.get_channel(CALL_PANEL_CHANNEL_ID)
        if channel is None:
            try:
                channel = await self.fetch_channel(CALL_PANEL_CHANNEL_ID)
            except discord.HTTPException:
                logger.exception("Unable to fetch call panel channel %s", CALL_PANEL_CHANNEL_ID)
                return

        if not isinstance(channel, discord.TextChannel):
            logger.error("CALL_PANEL_CHANNEL_ID %s is not a text channel", CALL_PANEL_CHANNEL_ID)
            return

        try:
            async for message in channel.history(limit=50):
                if message.author.id != self.user.id:
                    continue
                if message.embeds and message.embeds[0].title == "📢 MEMECOIN CALL PANEL":
                    logger.info("Existing call panel found: %s", message.id)
                    return
        except discord.HTTPException:
            logger.exception("Unable to inspect call panel history")
            return

        embed = discord.Embed(
            title="📢 MEMECOIN CALL PANEL",
            description=(
                "Submit the contract address of the memecoin you want to call.\n\n"
                "The first caller becomes the call owner and can stop the call later.\n"
                "Additional callers for the same CA are merged into the existing alert."
            ),
        )
        try:
            await channel.send(embed=embed, view=self.call_panel_view)
            logger.info("Call panel posted in #%s", channel.name)
        except discord.HTTPException:
            logger.exception("Unable to post call panel")

    async def close(self):
        await self.signal_manager.stop()
        self.db.close()
        await super().close()


bot = MemecoinBot()
bot.run(TOKEN)