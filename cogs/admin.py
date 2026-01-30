import discord
from discord.ext import commands, tasks
from discord import app_commands
import datetime

class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.status_index = 0
        self.status_list = [
            discord.Game(name="PsgFamily"),  # Playing
            discord.Activity(type=discord.ActivityType.watching, name="Moderation")
        ]

    # ========================
    # START STATUS LOOP
    # ========================
    @commands.Cog.listener()
    async def on_ready(self):
        if not self.status_loop.is_running():
            self.status_loop.start()
            print("✅ Status loop started (every 30s)")

    # ========================
    # STATUS LOOP
    # ========================
    @tasks.loop(seconds=30)
    async def status_loop(self):
        activity = self.status_list[self.status_index]
        await self.bot.change_presence(activity=activity)

        self.status_index += 1
        if self.status_index >= len(self.status_list):
            self.status_index = 0

    @status_loop.before_loop
    async def before_status_loop(self):
        await self.bot.wait_until_ready()

    # ========================
    # /ping
    # ========================
    @app_commands.command(name="ping", description="🏓 Check bot latency")
    async def ping(self, interaction: discord.Interaction):
        latency = round(self.bot.latency * 1000)
        await interaction.response.send_message(
            f"🏓 Pong! `{latency}ms`",
            ephemeral=True
        )

    # ========================
    # /playerinfo
    # ========================
    @app_commands.command(name="playerinfo", description="👤 Show user information")
    async def playerinfo(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user

        embed = discord.Embed(
            title="👤 Player Info",
            color=discord.Color.blue(),
            timestamp=datetime.datetime.utcnow()
        )

        embed.set_thumbnail(url=member.display_avatar.url)

        embed.add_field(name="Username", value=member.name, inline=True)
        embed.add_field(name="User ID", value=member.id, inline=True)
        embed.add_field(name="Joined Server", value=member.joined_at.strftime("%d-%m-%Y"), inline=False)
        embed.add_field(name="Account Created", value=member.created_at.strftime("%d-%m-%Y"), inline=False)
        embed.add_field(name="Top Role", value=member.top_role.mention, inline=False)

        await interaction.response.send_message(embed=embed)

    # ========================
    # /setstatus (manual override)
    # ========================
    @app_commands.command(name="setstatus", description="🤖 Set bot activity status manually")
    @app_commands.checks.has_permissions(administrator=True)
    async def setstatus(self, interaction: discord.Interaction, mode: str, text: str):
        await interaction.response.defer(ephemeral=True)

        mode = mode.lower()

        if mode == "playing":
            activity = discord.Game(name=text)
        elif mode == "watching":
            activity = discord.Activity(type=discord.ActivityType.watching, name=text)
        elif mode == "listening":
            activity = discord.Activity(type=discord.ActivityType.listening, name=text)
        else:
            return await interaction.followup.send(
                "❌ Mode must be: playing / watching / listening",
                ephemeral=True
            )

        await self.bot.change_presence(activity=activity)
        await interaction.followup.send(
            f"✅ Bot status set to **{mode} {text}**",
            ephemeral=True
        )


# ========================
# SETUP
# ========================
async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))
