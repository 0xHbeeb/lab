import os
import discord
from discord import app_commands
from discord.ext import commands


class CallModal(discord.ui.Modal, title="CALL MEMECOIN"):
    ca = discord.ui.TextInput(
        label="Contract Address",
        placeholder="Paste the memecoin contract address",
        required=True,
        max_length=128,
    )

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        ca = self.ca.value.strip()
        if not self.bot.token_service.validate_ca(ca):
            await interaction.response.send_message("❌ Invalid contract address format.", ephemeral=True)
            return
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("❌ This can only be used inside a server.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        try:
            signal, is_new = await self.bot.signal_manager.create_or_add_call(
                interaction.guild,
                interaction.user,
                ca,
                int(os.getenv("MEMECOIN_ALERT_CHANNEL_ID", "0")),
            )
        except Exception:
            import logging
            logging.getLogger("call-memecoin").exception("Call submission failed for CA=%s", ca)
            await interaction.followup.send("❌ Failed to create the memecoin call. Check the bot logs.", ephemeral=True)
            return

        action = "created" if is_new else "updated"
        alert_channel = self.bot.get_channel(signal.alert_channel_id)
        channel_text = alert_channel.mention if isinstance(alert_channel, discord.TextChannel) else "the alert channel"
        await interaction.followup.send(
            f"✅ Call {action} for **${signal.symbol}**. Alert posted in {channel_text}.",
            ephemeral=True,
        )


class StopModal(discord.ui.Modal, title="STOP CALL"):
    ca = discord.ui.TextInput(
        label="Contract Address",
        placeholder="Paste the exact CA you originally called",
        required=True,
        max_length=128,
    )

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        ca = self.ca.value.strip()
        if not self.bot.token_service.validate_ca(ca):
            await interaction.response.send_message("❌ Invalid contract address format.", ephemeral=True)
            return
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("❌ This can only be used inside a server.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        ok, message = await self.bot.signal_manager.stop_call(interaction.guild, interaction.user, ca)
        await interaction.followup.send(("✅ " if ok else "❌ ") + message, ephemeral=True)


class CallPanelView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="CALL MEMECOIN", style=discord.ButtonStyle.success, emoji="📢", custom_id="memecoin:call")
    async def call_memecoin(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CallModal(self.bot))

    @discord.ui.button(label="STOP CALL", style=discord.ButtonStyle.danger, emoji="🛑", custom_id="memecoin:stop")
    async def stop_call(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(StopModal(self.bot))


class CallMemecoinCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.view = CallPanelView(bot)
        self.bot.add_view(self.view)

    @app_commands.command(name="callpanel", description="Post the memecoin call panel in this channel")
    @app_commands.default_permissions(manage_guild=True)
    async def callpanel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📢 MEMECOIN CALL PANEL",
            description=(
                "Submit the contract address of the memecoin you want to call.\n\n"
                "The first caller becomes the call owner and can stop the call later.\n"
                "Additional callers for the same CA are merged into the existing alert."
            ),
        )
        await interaction.channel.send(embed=embed, view=self.view)
        await interaction.response.send_message("✅ Call panel posted.", ephemeral=True)