import discord
import aiosqlite
import time
from discord.ext import commands
from discord import app_commands

# =========================================================
# CONFIG
# =========================================================

# Auto mute duration after 3 warns (minutes)
AUTO_MUTE_MINUTES = 30

# Optional: role required to use moderation commands
# Set to None to allow admins/moderators by permission
MOD_ROLE_NAME = None   # e.g. "Moderator"

# =========================================================
# HELPERS
# =========================================================

async def get_modlog_channel(guild: discord.Guild):
    async with aiosqlite.connect("bot.db") as db:
        cur = await db.execute(
            "SELECT modlog_channel FROM guild_settings WHERE guild_id=?",
            (guild.id,)
        )
        row = await cur.fetchone()
        if not row or not row[0]:
            return None
        return guild.get_channel(row[0])

async def add_warn(user_id: int, guild_id: int):
    async with aiosqlite.connect("bot.db") as db:
        await db.execute(
            "INSERT OR IGNORE INTO warnings (user_id, guild_id, count) VALUES (?,?,0)",
            (user_id, guild_id)
        )
        await db.execute(
            "UPDATE warnings SET count = count + 1 WHERE user_id=? AND guild_id=?",
            (user_id, guild_id)
        )
        await db.commit()

async def get_warns(user_id: int, guild_id: int) -> int:
    async with aiosqlite.connect("bot.db") as db:
        cur = await db.execute(
            "SELECT count FROM warnings WHERE user_id=? AND guild_id=?",
            (user_id, guild_id)
        )
        row = await cur.fetchone()
        return row[0] if row else 0

async def reset_warns(user_id: int, guild_id: int):
    async with aiosqlite.connect("bot.db") as db:
        await db.execute(
            "DELETE FROM warnings WHERE user_id=? AND guild_id=?",
            (user_id, guild_id)
        )
        await db.commit()

def mod_permission_check(interaction: discord.Interaction):
    if MOD_ROLE_NAME:
        role = discord.utils.get(interaction.guild.roles, name=MOD_ROLE_NAME)
        return role in interaction.user.roles
    return interaction.user.guild_permissions.moderate_members

# =========================================================
# MODERATION COG
# =========================================================

class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -----------------------------------------------------
    # /kick
    # -----------------------------------------------------
    @app_commands.command(name="kick", description="👢 Kick a member")
    async def kick(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "No reason provided"
    ):
        if not mod_permission_check(interaction):
            return await interaction.response.send_message(
                "❌ You don't have permission.",
                ephemeral=True
            )

        await member.kick(reason=reason)

        await interaction.response.send_message(
            f"👢 {member.mention} kicked.\nReason: {reason}",
            ephemeral=True
        )

        await self.send_log(interaction.guild, f"👢 **Kick**\n{member} — {reason}")

    # -----------------------------------------------------
    # /ban
    # -----------------------------------------------------
    @app_commands.command(name="ban", description="🔨 Ban a member")
    async def ban(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "No reason provided"
    ):
        if not mod_permission_check(interaction):
            return await interaction.response.send_message(
                "❌ You don't have permission.",
                ephemeral=True
            )

        await member.ban(reason=reason)

        await interaction.response.send_message(
            f"🔨 {member.mention} banned.\nReason: {reason}",
            ephemeral=True
        )

        await self.send_log(interaction.guild, f"🔨 **Ban**\n{member} — {reason}")

    # -----------------------------------------------------
    # /unban
    # -----------------------------------------------------
    @app_commands.command(name="unban", description="♻️ Unban a user")
    async def unban(
        self,
        interaction: discord.Interaction,
        user_id: int
    ):
        if not mod_permission_check(interaction):
            return await interaction.response.send_message(
                "❌ You don't have permission.",
                ephemeral=True
            )

        user = await self.bot.fetch_user(user_id)
        await interaction.guild.unban(user)

        await interaction.response.send_message(
            f"♻️ {user} unbanned.",
            ephemeral=True
        )

        await self.send_log(interaction.guild, f"♻️ **Unban**\n{user}")

    # -----------------------------------------------------
    # /timeout
    # -----------------------------------------------------
    @app_commands.command(name="timeout", description="⏳ Timeout (mute) a member")
    async def timeout(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        minutes: int,
        reason: str = "No reason provided"
    ):
        if not mod_permission_check(interaction):
            return await interaction.response.send_message(
                "❌ You don't have permission.",
                ephemeral=True
            )

        until = discord.utils.utcnow() + discord.timedelta(minutes=minutes)
        await member.timeout(until, reason=reason)

        await interaction.response.send_message(
            f"⏳ {member.mention} timed out for **{minutes} minutes**.",
            ephemeral=True
        )

        await self.send_log(
            interaction.guild,
            f"⏳ **Timeout**\n{member} — {minutes} min — {reason}"
        )

    # -----------------------------------------------------
    # /warn
    # -----------------------------------------------------
    @app_commands.command(name="warn", description="⚠️ Warn a member")
    async def warn(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "No reason provided"
    ):
        if not mod_permission_check(interaction):
            return await interaction.response.send_message(
                "❌ You don't have permission.",
                ephemeral=True
            )

        await add_warn(member.id, interaction.guild.id)
        count = await get_warns(member.id, interaction.guild.id)

        await interaction.response.send_message(
            f"⚠️ {member.mention} warned.\nTotal warns: **{count}**",
            ephemeral=True
        )

        await self.send_log(
            interaction.guild,
            f"⚠️ **Warn**\n{member} — {reason} ({count}/3)"
        )

        # Auto mute after 3 warns
        if count >= 3:
            until = discord.utils.utcnow() + discord.timedelta(minutes=AUTO_MUTE_MINUTES)
            await member.timeout(until, reason="Auto mute: 3 warnings")
            await reset_warns(member.id, interaction.guild.id)

            await self.send_log(
                interaction.guild,
                f"🔇 **Auto Mute**\n{member} — {AUTO_MUTE_MINUTES} minutes (3 warns)"
            )

    # -----------------------------------------------------
    # /warns
    # -----------------------------------------------------
    @app_commands.command(name="warns", description="📋 View member warnings")
    async def warns(
        self,
        interaction: discord.Interaction,
        member: discord.Member
    ):
        count = await get_warns(member.id, interaction.guild.id)
        await interaction.response.send_message(
            f"📋 {member.mention} has **{count} warnings**.",
            ephemeral=True
        )

    # -----------------------------------------------------
    # MOD LOG SENDER
    # -----------------------------------------------------
    async def send_log(self, guild: discord.Guild, text: str):
        channel = await get_modlog_channel(guild)
        if channel:
            await channel.send(text)

# =========================================================
# SETUP
# =========================================================

async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
