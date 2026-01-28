import discord
import aiosqlite
import time
from discord.ext import commands, tasks
from discord import app_commands

# =========================================================
# CONFIG
# =========================================================

# Replace with your real role IDs
PREMIUM_ROLES = {
    "bronze": 1463834717987274814,
    "silver": 1463884119032463433,
    "gold":   1463884209025187880
}

# =========================================================
# PREMIUM COG
# =========================================================

class Premium(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.expiry_loop.start()

    # -----------------------------------------------------
    # AUTO EXPIRY CHECK (EVERY MINUTE)
    # -----------------------------------------------------
    @tasks.loop(minutes=1)
    async def expiry_loop(self):
        now = int(time.time())

        async with aiosqlite.connect("bot.db") as db:
            cur = await db.execute(
                "SELECT user_id, tier FROM premium WHERE expires < ?",
                (now,)
            )
            expired = await cur.fetchall()

            for user_id, tier in expired:
                for guild in self.bot.guilds:
                    member = guild.get_member(user_id)
                    if not member:
                        continue

                    role_id = PREMIUM_ROLES.get(tier)
                    if role_id:
                        role = guild.get_role(role_id)
                        if role:
                            try:
                                await member.remove_roles(role, reason="Premium expired")
                            except:
                                pass

                await db.execute(
                    "DELETE FROM premium WHERE user_id=?",
                    (user_id,)
                )

            await db.commit()

    # -----------------------------------------------------
    # /premium — USER STATUS
    # -----------------------------------------------------
    @app_commands.command(name="premium", description="💎 View your premium status")
    async def premium(self, interaction: discord.Interaction):
        async with aiosqlite.connect("bot.db") as db:
            cur = await db.execute(
                "SELECT tier, expires FROM premium WHERE user_id=?",
                (interaction.user.id,)
            )
            row = await cur.fetchone()

        if not row:
            return await interaction.response.send_message(
                "❌ You do not have premium.",
                ephemeral=True
            )

        tier, expires = row
        remaining = expires - int(time.time())
        days = max(0, remaining // 86400)

        embed = discord.Embed(
            title="💎 Premium Status",
            color=discord.Color.gold()
        )
        embed.add_field(name="Tier", value=tier.title())
        embed.add_field(name="Expires In", value=f"{days} days")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # -----------------------------------------------------
    # ADMIN: GRANT PREMIUM
    # -----------------------------------------------------
    @app_commands.command(name="grant_premium", description="👑 Grant premium to a user")
    @app_commands.checks.has_permissions(administrator=True)
    async def grant_premium(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        tier: str,
        days: int
    ):
        tier = tier.lower()
        if tier not in PREMIUM_ROLES:
            return await interaction.response.send_message(
                "❌ Invalid tier.",
                ephemeral=True
            )

        expires = int(time.time()) + days * 86400

        async with aiosqlite.connect("bot.db") as db:
            await db.execute(
                """
                INSERT INTO premium (user_id, tier, expires)
                VALUES (?,?,?)
                ON CONFLICT(user_id)
                DO UPDATE SET tier=excluded.tier, expires=excluded.expires
                """,
                (member.id, tier, expires)
            )
            await db.commit()

        role = interaction.guild.get_role(PREMIUM_ROLES[tier])
        if role:
            try:
                await member.add_roles(role, reason="Premium granted")
            except:
                pass

        await interaction.response.send_message(
            f"✅ Granted **{tier.title()} Premium** to {member.mention} for **{days} days**",
            ephemeral=True
        )

    # -----------------------------------------------------
    # ADMIN: REMOVE PREMIUM
    # -----------------------------------------------------
    @app_commands.command(name="remove_premium", description="❌ Remove premium from a user")
    @app_commands.checks.has_permissions(administrator=True)
    async def remove_premium(
        self,
        interaction: discord.Interaction,
        member: discord.Member
    ):
        async with aiosqlite.connect("bot.db") as db:
            cur = await db.execute(
                "SELECT tier FROM premium WHERE user_id=?",
                (member.id,)
            )
            row = await cur.fetchone()

            if not row:
                return await interaction.response.send_message(
                    "❌ User does not have premium.",
                    ephemeral=True
                )

            tier = row[0]

            await db.execute(
                "DELETE FROM premium WHERE user_id=?",
                (member.id,)
            )
            await db.commit()

        role = interaction.guild.get_role(PREMIUM_ROLES.get(tier))
        if role:
            try:
                await member.remove_roles(role, reason="Premium removed")
            except:
                pass

        await interaction.response.send_message(
            f"✅ Removed premium from {member.mention}",
            ephemeral=True
        )

# =========================================================
# SETUP
# =========================================================

async def setup(bot: commands.Bot):
    await bot.add_cog(Premium(bot))
