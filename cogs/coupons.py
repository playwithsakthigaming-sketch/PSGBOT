import discord
import aiosqlite
import time
from discord.ext import commands
from discord import app_commands

# =========================================================
# COUPON TYPES
# =========================================================
# type = "coins" or "premium"
# value = discount value
#   coins   -> flat coin discount
#   premium -> percentage discount (10 = 10%)
# max_uses = total uses allowed
# expires  = unix timestamp (0 = never)

# =========================================================
# HELPERS
# =========================================================

async def get_coupon(code: str):
    async with aiosqlite.connect("bot.db") as db:
        cur = await db.execute(
            "SELECT code, type, value, max_uses, used, expires FROM coupons WHERE code=?",
            (code.upper(),)
        )
        return await cur.fetchone()

async def use_coupon(code: str):
    async with aiosqlite.connect("bot.db") as db:
        await db.execute(
            "UPDATE coupons SET used = used + 1 WHERE code=?",
            (code.upper(),)
        )
        await db.commit()

# =========================================================
# COG
# =========================================================

class Coupons(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -----------------------------------------------------
    # ADMIN: CREATE COUPON
    # -----------------------------------------------------
    @app_commands.command(name="create_coupon", description="🎟️ Create a discount coupon")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        code="Coupon code (example: PSG50)",
        coupon_type="coins or premium",
        value="Discount value (coins or %)",
        max_uses="Max number of uses",
        days_valid="Days until expiry (0 = never)"
    )
    async def create_coupon(
        self,
        interaction: discord.Interaction,
        code: str,
        coupon_type: str,
        value: int,
        max_uses: int,
        days_valid: int = 0
    ):
        coupon_type = coupon_type.lower()
        if coupon_type not in ["coins", "premium"]:
            return await interaction.response.send_message(
                "❌ coupon_type must be `coins` or `premium`",
                ephemeral=True
            )

        expires = 0
        if days_valid > 0:
            expires = int(time.time()) + days_valid * 86400

        async with aiosqlite.connect("bot.db") as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO coupons
                (code, type, value, max_uses, used, expires)
                VALUES (?,?,?,?,0,?)
                """,
                (code.upper(), coupon_type, value, max_uses, expires)
            )
            await db.commit()

        await interaction.response.send_message(
            f"✅ Coupon **{code.upper()}** created!",
            ephemeral=True
        )

    # -----------------------------------------------------
    # ADMIN: DELETE COUPON
    # -----------------------------------------------------
    @app_commands.command(name="delete_coupon", description="❌ Delete a coupon")
    @app_commands.checks.has_permissions(administrator=True)
    async def delete_coupon(self, interaction: discord.Interaction, code: str):
        async with aiosqlite.connect("bot.db") as db:
            await db.execute(
                "DELETE FROM coupons WHERE code=?",
                (code.upper(),)
            )
            await db.commit()

        await interaction.response.send_message(
            f"❌ Coupon **{code.upper()}** deleted.",
            ephemeral=True
        )

    # -----------------------------------------------------
    # USER: CHECK COUPON
    # -----------------------------------------------------
    @app_commands.command(name="coupon", description="🎟️ Check a coupon code")
    async def coupon(self, interaction: discord.Interaction, code: str):
        data = await get_coupon(code)
        if not data:
            return await interaction.response.send_message(
                "❌ Invalid coupon.",
                ephemeral=True
            )

        _, ctype, value, max_uses, used, expires = data

        if expires and expires < int(time.time()):
            return await interaction.response.send_message(
                "❌ Coupon expired.",
                ephemeral=True
            )

        if used >= max_uses:
            return await interaction.response.send_message(
                "❌ Coupon usage limit reached.",
                ephemeral=True
            )

        embed = discord.Embed(
            title="🎟️ Coupon Details",
            color=discord.Color.gold()
        )
        embed.add_field(name="Code", value=code.upper())
        embed.add_field(name="Type", value=ctype.title())
        embed.add_field(
            name="Value",
            value=f"{value} coins" if ctype == "coins" else f"{value}% premium discount"
        )
        embed.add_field(name="Uses", value=f"{used}/{max_uses}")
        embed.add_field(
            name="Expires",
            value="Never" if expires == 0 else f"<t:{expires}:R>"
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

# =========================================================
# SETUP
# =========================================================

async def setup(bot: commands.Bot):
    await bot.add_cog(Coupons(bot))
