import discord
from discord.ext import commands, tasks
from discord import app_commands
import datetime
import os, sys, time, aiohttp

START_TIME = time.time()
CHANGELOG_CHANNEL_NAME = "changelog"  # create this channel in your server

# ========================
# SERVER STATUS VIEW
# ========================
class ServerStatusView(discord.ui.View):
    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=300)
        self.guild = guild

    def get_embed(self):
        online = sum(m.status != discord.Status.offline for m in self.guild.members)

        embed = discord.Embed(
            title="📊 Server Status",
            color=discord.Color.green(),
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name="Server", value=self.guild.name, inline=False)
        embed.add_field(name="Members", value=self.guild.member_count, inline=True)
        embed.add_field(name="Online", value=online, inline=True)
        embed.add_field(name="Channels", value=len(self.guild.channels), inline=True)
        embed.add_field(name="Roles", value=len(self.guild.roles), inline=True)

        if self.guild.icon:
            embed.set_thumbnail(url=self.guild.icon.url)

        return embed

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.green, emoji="🔄")
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = self.get_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Remove", style=discord.ButtonStyle.red, emoji="🗑")
    async def remove(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.message.delete()


class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.status_index = 0
        self.status_list = [
            discord.Game(name="Watching moderation and activity"),
            discord.Activity(type=discord.ActivityType.watching, name="premium member security"),
            discord.Game(name="Playing Play With Sakthi Gaming")
        ]

    # ========================
    # READY
    # ========================
    @commands.Cog.listener()
    async def on_ready(self):
        if not self.status_loop.is_running():
            self.status_loop.start()
            print("✅ Status rotation started")

    # ========================
    # STATUS LOOP
    # ========================
    @tasks.loop(seconds=10)
    async def status_loop(self):
        activity = self.status_list[self.status_index]
        await self.bot.change_presence(activity=activity)
        self.status_index = (self.status_index + 1) % len(self.status_list)

    @status_loop.before_loop
    async def before_status_loop(self):
        await self.bot.wait_until_ready()

    # ========================
    # /ping
    # ========================
    @app_commands.command(name="ping", description="Check bot latency")
    async def ping(self, interaction: discord.Interaction):
        latency = round(self.bot.latency * 1000)
        await interaction.response.send_message(f"🏓 Pong! `{latency}ms`", ephemeral=True)

    # ========================
    # /serverstatus
    # ========================
    @app_commands.command(name="serverstatus", description="Show server status with buttons")
    async def serverstatus(self, interaction: discord.Interaction):
        view = ServerStatusView(interaction.guild)
        embed = view.get_embed()
        await interaction.response.send_message(embed=embed, view=view)

    # ========================
    # CHANGELOG LOGGER
    # ========================
    async def send_changelog(self, guild: discord.Guild, embed: discord.Embed):
        channel = discord.utils.get(guild.text_channels, name=CHANGELOG_CHANNEL_NAME)
        if channel:
            await channel.send(embed=embed)

    # ========================
    # /delete_channel
    # ========================
    @app_commands.command(name="delete_channel", description="🗑 Delete a channel and log it")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def delete_channel(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel = None,
        reason: str = "No reason provided"
    ):
        await interaction.response.defer(ephemeral=True)

        channel = channel or interaction.channel

        embed = discord.Embed(
            title="📜 Channel Deleted",
            color=discord.Color.red(),
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name="Channel", value=channel.name, inline=False)
        embed.add_field(name="Deleted By", value=interaction.user.mention, inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)

        await self.send_changelog(interaction.guild, embed)

        await channel.delete(reason=f"{interaction.user} - {reason}")

        await interaction.followup.send("✅ Channel deleted and logged in changelog.", ephemeral=True)

    # ========================
    # CLEAR CHAT
    # ========================
    @app_commands.command(name="clear_chat", description="🧹 Clear messages")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clear_chat(self, interaction: discord.Interaction, amount: int):
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(
            f"🧹 Deleted {len(deleted)} messages",
            ephemeral=True
        )


# ========================
# SETUP
# ========================
async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))
