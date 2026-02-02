import discord
from discord.ext import commands
from discord import app_commands
import datetime
import random
import asyncio
import time
import aiosqlite   # ✅ FIX
# ========================
# CONFIG
# ========================
CHANGELOG_CHANNEL_ID = 123456789012345678
DM_DELAY = 2
START_TIME = time.time()
DB_NAME = "bot.db"   # ✅ FIX


# ========================
# CONFIRM VIEW
# ========================
class ConfirmView(discord.ui.View):
    def __init__(self, callback):
        super().__init__(timeout=60)
        self.callback = callback

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await self.callback()
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("❌ Action cancelled.", ephemeral=True)
        self.stop()


# ========================
# SELF ROLE SYSTEM
# ========================
class SelfRoleButton(discord.ui.Button):
    def __init__(self, role: discord.Role, emoji: str):
        super().__init__(label="", style=discord.ButtonStyle.primary, emoji=emoji)
        self.role = role

    async def callback(self, interaction: discord.Interaction):
        member = interaction.user
        if self.role in member.roles:
            await member.remove_roles(self.role)
            await interaction.response.send_message(f"❌ Removed **{self.role.name}**", ephemeral=True)
        else:
            await member.add_roles(self.role)
            await interaction.response.send_message(f"✅ Added **{self.role.name}**", ephemeral=True)


class SelfRoleView(discord.ui.View):
    def __init__(self, pairs):
        super().__init__(timeout=None)
        for role, emoji in pairs:
            self.add_item(SelfRoleButton(role, emoji))


# ========================
# GIVEAWAY VIEW
# ========================
class GiveawayView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.participants = set()

    @discord.ui.button(label="Join Giveaway", style=discord.ButtonStyle.green, emoji="🎉")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id in self.participants:
            return await interaction.response.send_message("❌ Already joined!", ephemeral=True)

        self.participants.add(interaction.user.id)
        await interaction.response.send_message("✅ Joined giveaway!", ephemeral=True)


# ========================
# ADMIN COG
# ========================
class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.giveaways = {}

    async def send_changelog(self, embed: discord.Embed):
        channel = self.bot.get_channel(CHANGELOG_CHANNEL_ID)
        if channel:
            await channel.send(embed=embed)

    # ========================
    # PING
    # ========================
    @app_commands.command(name="ping")
    async def ping(self, interaction: discord.Interaction):
        latency = round(self.bot.latency * 1000)
        await interaction.response.send_message(f"🏓 Pong `{latency}ms`", ephemeral=True)

    # ========================
    # SERVER STATUS
    # ========================
    @app_commands.command(name="serverstatus")
    async def serverstatus(self, interaction: discord.Interaction):
        guild = interaction.guild
        online = sum(m.status != discord.Status.offline for m in guild.members)

        embed = discord.Embed(title="📊 Server Status", color=discord.Color.green())
        embed.add_field(name="Server", value=guild.name)
        embed.add_field(name="Members", value=guild.member_count)
        embed.add_field(name="Online", value=online)
        embed.add_field(name="Channels", value=len(guild.channels))
        embed.add_field(name="Roles", value=len(guild.roles))
        embed.add_field(name="Boost Level", value=guild.premium_tier)

        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        await interaction.response.send_message(embed=embed)

    # ========================
    # BOT INFO
    # ========================
    @app_commands.command(name="botinfo")
    async def botinfo(self, interaction: discord.Interaction):
        uptime = int(time.time() - START_TIME)

        embed = discord.Embed(title="🤖 Bot Information", color=discord.Color.blue())
        embed.add_field(name="Servers", value=len(self.bot.guilds))
        embed.add_field(name="Users", value=len(self.bot.users))
        embed.add_field(name="Latency", value=f"{round(self.bot.latency*1000)}ms")
        embed.add_field(name="Uptime", value=f"{uptime//3600}h {(uptime%3600)//60}m")

        await interaction.response.send_message(embed=embed)

    # ========================
    # PLAYER INFO (FIXED)
    # ========================
    @app_commands.command(name="playerinfo")
    async def playerinfo(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user

        premium_status = "❌ No"
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute("SELECT tier FROM premium WHERE user_id=?", (member.id,))
            row = await cursor.fetchone()
            if row:
                premium_status = f"✅ {row[0]}"

        nitro_status = "✨ Yes" if member.avatar and member.avatar.is_animated() else "❌ No"
        boost_status = "💎 Yes" if member.premium_since else "❌ No"

        joined = member.joined_at.strftime("%d-%m-%Y") if member.joined_at else "Unknown"
        created = member.created_at.strftime("%d-%m-%Y")

        embed = discord.Embed(title="👤 Player Info", color=discord.Color.blue())
        embed.set_thumbnail(url=member.display_avatar.url)

        embed.add_field(name="Username", value=member.name)
        embed.add_field(name="User ID", value=member.id)
        embed.add_field(name="DB Premium", value=premium_status)
        embed.add_field(name="Nitro", value=nitro_status)
        embed.add_field(name="Server Booster", value=boost_status)
        embed.add_field(name="Joined Server", value=joined)
        embed.add_field(name="Account Created", value=created)
        embed.add_field(name="Top Role", value=member.top_role.mention)

        await interaction.response.send_message(embed=embed)

    # ========================
    # CLEAR CHAT
    # ========================
    @app_commands.command(name="clear_chat")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clear_chat(self, interaction: discord.Interaction, amount: int):
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"🧹 Deleted {len(deleted)} messages", ephemeral=True)

    # ========================
    # DELETE CHANNEL
    # ========================
    @app_commands.command(name="delete_channel")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def delete_channel(self, interaction: discord.Interaction, reason: str = "No reason"):
        embed = discord.Embed(title="📜 Channel Deleted", color=discord.Color.red())
        embed.add_field(name="Channel", value=interaction.channel.name)
        embed.add_field(name="By", value=interaction.user.mention)
        embed.add_field(name="Reason", value=reason)

        await self.send_changelog(embed)
        await interaction.channel.delete(reason=reason)


# ========================
# SETUP
# ========================
async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))
