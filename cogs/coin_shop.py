import discord
import time, aiosqlite
from discord.ext import commands, tasks
from discord import app_commands

DB_NAME = "bot.db"

# ================= CONFIG =================
PRICES = {"bronze": 100, "silver": 200, "gold": 300}
DAYS = {"bronze": 3, "silver": 5, "gold": 7}

PREMIUM_ROLE_IDS = {
    "bronze": 1463834717987274814,
    "silver": 1463884119032463433,
    "gold": 1463884209025187880
}

LOGO_URL = "https://files.catbox.moe/mrpfrf.webp"


# ================= BUY MODAL =================
class BuyPremiumModal(discord.ui.Modal):
    def __init__(self, tier):
        super().__init__(title=f"Buy {tier.capitalize()} Premium")
        self.tier = tier

        self.name = discord.ui.TextInput(label="Your Name")
        self.coupon = discord.ui.TextInput(
            label="Coupon Code (optional)",
            required=False
        )

        self.add_item(self.name)
        self.add_item(self.coupon)

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        tier = self.tier
        base_price = PRICES[tier]
        discount = 0

        coupon_code = self.coupon.value.strip().upper()

        # ===== COUPON CHECK =====
        if coupon_code:
            async with aiosqlite.connect(DB_NAME) as db:
                async with db.execute(
                    "SELECT type,value,max_uses,used,expires FROM coupons WHERE code=?",
                    (coupon_code,)
                ) as cur:
                    row = await cur.fetchone()

            if not row:
                return await interaction.response.send_message("❌ Invalid coupon.", ephemeral=True)

            ctype, value, max_uses, used, expires = row

            if expires and expires < int(time.time()):
                return await interaction.response.send_message("❌ Coupon expired.", ephemeral=True)

            if used >= max_uses:
                return await interaction.response.send_message("❌ Coupon limit reached.", ephemeral=True)

            if ctype == "percent":
                discount = int(base_price * (value / 100))
            elif ctype == "flat":
                discount = value

        final_price = max(base_price - discount, 0)

        # ===== BALANCE CHECK =====
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT balance FROM coins WHERE user_id=?", (user_id,)) as cur:
                row = await cur.fetchone()
                balance = row[0] if row else 0

        if balance < final_price:
            return await interaction.response.send_message(
                f"❌ Not enough coins. Need `{final_price}` coins.",
                ephemeral=True
            )

        expires = int(time.time()) + DAYS[tier] * 86400

        # ===== APPLY PURCHASE =====
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("UPDATE coins SET balance=balance-? WHERE user_id=?", (final_price, user_id))
            await db.execute(
                "INSERT OR REPLACE INTO premium (user_id,tier,expires) VALUES (?,?,?)",
                (user_id, tier, expires)
            )

            if coupon_code:
                await db.execute("UPDATE coupons SET used = used + 1 WHERE code=?", (coupon_code,))

            await db.commit()

        role = interaction.guild.get_role(PREMIUM_ROLE_IDS[tier])
        if role:
            await interaction.user.add_roles(role)

        await interaction.response.send_message(
            f"✅ **Thank you for purchasing {tier.capitalize()} Premium!**\n"
            f"🪙 Coins Used: **{final_price}**\n"
            f"⏳ Duration: **{DAYS[tier]} days**",
            ephemeral=True
        )


# ================= RENEW BUTTON VIEW =================
class RenewView(discord.ui.View):
    def __init__(self, tier):
        super().__init__(timeout=None)
        self.tier = tier

    @discord.ui.button(label="Renew Premium", style=discord.ButtonStyle.success, emoji="🔄")
    async def renew(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BuyPremiumModal(self.tier))


# ================= SHOP BUTTON VIEW =================
class CoinShopView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Bronze (3 Days)", emoji="🥉", style=discord.ButtonStyle.secondary, custom_id="buy_bronze")
    async def bronze(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BuyPremiumModal("bronze"))

    @discord.ui.button(label="Silver (5 Days)", emoji="🥈", style=discord.ButtonStyle.primary, custom_id="buy_silver")
    async def silver(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BuyPremiumModal("silver"))

    @discord.ui.button(label="Gold (7 Days)", emoji="🥇", style=discord.ButtonStyle.success, custom_id="buy_gold")
    async def gold(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BuyPremiumModal("gold"))


# ================= COG =================
class CoinShop(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.expiry_task.start()

    @app_commands.command(name="coin_shop_panel", description="Create premium shop panel")
    async def coin_shop_panel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

        embed = discord.Embed(
            title="👑 PSG Family Premium Shop",
            description=(
                "🥉 Bronze – 100 Coins (3 Days)\n"
                "🥈 Silver – 200 Coins (5 Days)\n"
                "🥇 Gold – 300 Coins (7 Days)\n\n"
                "🎟 Coupon supported\n"
                "Click a button below to buy premium."
            ),
            color=discord.Color.gold()
        )
        embed.set_thumbnail(url=LOGO_URL)

        await channel.send(embed=embed, view=CoinShopView())
        await interaction.response.send_message("✅ Coin shop panel created.", ephemeral=True)

    # ================= AUTO EXPIRY + REMINDER =================
    @tasks.loop(minutes=1)
    async def expiry_task(self):
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT user_id,tier,expires FROM premium") as cur:
                rows = await cur.fetchall()

        now = int(time.time())

        for user_id, tier, expires in rows:
            remaining = expires - now

            # ===== 1 DAY REMINDER WITH BUTTON =====
            if 86000 <= remaining <= 86400:
                user = self.bot.get_user(user_id)
                if user:
                    try:
                        await user.send(
                            f"⏰ **Your {tier.capitalize()} Premium will expire in 1 day.**\n"
                            "Click below to renew.",
                            view=RenewView(tier)
                        )
                    except:
                        pass

            # ===== EXPIRED =====
            if expires <= now:
                async with aiosqlite.connect(DB_NAME) as db:
                    await db.execute("DELETE FROM premium WHERE user_id=?", (user_id,))
                    await db.commit()

                for guild in self.bot.guilds:
                    member = guild.get_member(user_id)
                    if member:
                        role = guild.get_role(PREMIUM_ROLE_IDS[tier])
                        if role:
                            await member.remove_roles(role)

    @expiry_task.before_loop
    async def before_expiry(self):
        await self.bot.wait_until_ready()


# ================= SETUP =================
async def setup(bot):
    bot.add_view(CoinShopView())
    await bot.add_cog(CoinShop(bot))
