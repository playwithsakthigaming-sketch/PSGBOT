import discord
from discord.ext import commands, tasks
from discord import app_commands
import datetime
import aiosqlite
import os
import sys
import time

DB_NAME = "bot.db"
START_TIME = time.time()

class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.status_index = 0
        self.status_list = [
            discord.Game(name="Watching Modration and activity"),
            discord.Activity(type=discord.ActivityType.watching, name="premium member security"),
            discord.Game(name="playing play with sakthi gaming")
        ]

    # ========================
    # BOT READY
    # ========================
    @commands.Cog.listener()
    async def on_ready(self):
        if not self.status_loop.is_running():
            self.status_loop.start()
            print("✅ Status rotation started (10s)")

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
    @app_commands.command(name="ping", description="🏓 Check bot latency")
    async def ping(self, interaction: discord.Interaction):
        latency = round(self.bot.latency * 1000)
        await interaction.response.send_message(
            f"🏓 Pong! `{latency}ms`",
            ephemeral=True
        )

    # ========================
    # /botinfo
    # ========================
    @app_commands.command(name="botinfo", description="🤖 Show bot information")
    async def botinfo(self, interaction: discord.Interaction):
        uptime = int(time.time() - START_TIME)

        embed = discord.Embed(
            title="🤖 Bot Info",
            color=discord.Color.gold(),
            timestamp=datetime.datetime.utcnow()
        )

        embed.add_field(name="Servers", value=len(self.bot.guilds), inline=True)
        embed.add_field(name="Users", value=len(self.bot.users), inline=True)
        embed.add_field(name="Latency", value=f"{round(self.bot.latency*1000)}ms", inline=True)
        embed.add_field(
            name="Uptime",
            value=f"{uptime//3600}h {(uptime%3600)//60}m",
            inline=True
        )

        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    # ========================
    # /serverstatus
    # ========================
    @app_commands.command(name="serverstatus", description="📊 Show server status")
    async def serverstatus(self, interaction: discord.Interaction):
        guild = interaction.guild
        online = sum(m.status != discord.Status.offline for m in guild.members)

        embed = discord.Embed(
            title="📊 Server Status",
            color=discord.Color.green(),
            timestamp=datetime.datetime.utcnow()
        )

        embed.add_field(name="Server", value=guild.name, inline=False)
        embed.add_field(name="Members", value=guild.member_count, inline=True)
        embed.add_field(name="Online", value=online, inline=True)
        embed.add_field(name="Channels", value=len(guild.channels), inline=True)
        embed.add_field(name="Roles", value=len(guild.roles), inline=True)
        embed.add_field(name="Boost Level", value=guild.premium_tier, inline=True)

        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        await interaction.response.send_message(embed=embed)

    # ========================
    # /playerinfo (UPDATED)
    # ========================
    @app_commands.command(name="playerinfo", description="👤 Show user information")
    async def playerinfo(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user

        # Premium from DB
        premium_status = "❌ No"
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute("SELECT tier FROM premium WHERE user_id=?", (member.id,))
            row = await cursor.fetchone()
            if row:
                premium_status = f"✅ {row[0].capitalize()}"

        # Nitro detection (animated avatar)
        nitro_status = "❌ No"
        if member.avatar and member.avatar.is_animated():
            nitro_status = "✨ Yes"

        # Server boost status
        boost_status = "❌ No"
        if member.premium_since:
            boost_status = "💎 Yes"

        embed = discord.Embed(
            title="👤 Player Info",
            color=discord.Color.blue(),
            timestamp=datetime.datetime.utcnow()
        )

        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Username", value=member.name, inline=True)
        embed.add_field(name="User ID", value=member.id, inline=True)
        embed.add_field(name="Premium", value=premium_status, inline=True)
        embed.add_field(name="Nitro", value=nitro_status, inline=True)
        embed.add_field(name="Server Booster", value=boost_status, inline=True)
        embed.add_field(name="Joined Server", value=member.joined_at.strftime("%d-%m-%Y"), inline=False)
        embed.add_field(name="Account Created", value=member.created_at.strftime("%d-%m-%Y"), inline=False)
        embed.add_field(name="Top Role", value=member.top_role.mention, inline=False)

        await interaction.response.send_message(embed=embed)

    # ========================
    # /setstatus
    # ========================
    @app_commands.command(name="setstatus", description="🤖 Set bot activity manually")
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
            f"✅ Bot status updated to **{mode} {text}**",
            ephemeral=True
        )

    # ========================
    # /restart
    # ========================
    @app_commands.command(name="restart", description="♻ Restart the bot")
    @app_commands.checks.has_permissions(administrator=True)
    async def restart(self, interaction: discord.Interaction):
        await interaction.response.send_message("♻ Restarting bot...", ephemeral=True)
        os.execv(sys.executable, ["python"] + sys.argv)

    # ========================
    # /dm
    # ========================
    @app_commands.command(name="dm", description="✉ Send DM to a user")
    @app_commands.checks.has_permissions(administrator=True)
    async def dm(self, interaction: discord.Interaction, member: discord.Member, message: str):
        try:
            await member.send(message)
            await interaction.response.send_message("✅ DM sent", ephemeral=True)
        except:
            await interaction.response.send_message("❌ Could not send DM", ephemeral=True)

    # ========================
    # /dmall
    # ========================
    @app_commands.command(name="dmall", description="📢 DM all server members")
    @app_commands.checks.has_permissions(administrator=True)
    async def dmall(self, interaction: discord.Interaction, message: str):
        await interaction.response.defer(ephemeral=True)
        count = 0
        for member in interaction.guild.members:
            if not member.bot:
                try:
                    await member.send(message)
                    count += 1
                except:
                    pass
        await interaction.followup.send(f"✅ Sent DM to {count} members", ephemeral=True)

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
