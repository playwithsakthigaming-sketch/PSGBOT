import discord
import time, random, aiosqlite, requests
from discord.ext import commands, tasks
from discord import app_commands
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

DB_NAME = "bot.db"

# ================= CONFIG =================
PRICES = {"bronze": 100, "silver": 200, "gold": 300}
DAYS = {"bronze": 3, "silver": 5, "gold": 7}

PREMIUM_ROLE_IDS = {
    "bronze": 1463834717987274814,
    "silver": 1463884119032463433,
    "gold": 1463884209025187880
}

LOGO_URL = "https://media.discordapp.net/attachments/1116720480544636999/1465307326985535520/Untitled_design.png?ex=6978a14a&is=69774fca&hm=3554648e7b48a65b29082a3b4611787d16cebc668cc35618c0c16c19a2f304d2&=&format=webp&quality=lossless&width=1202&height=676"


# ================= PREMIUM INVOICE IMAGE =================
def generate_premium_invoice(username: str, tier: str, days: int, coins: int):
    W, H = 1000, 650
    img = Image.new("RGB", (W, H), (10, 10, 10))
    draw = ImageDraw.Draw(img)

    gold = (255, 200, 60)
    white = (255, 255, 255)
    green = (0, 255, 0)

    try:
        title_font = ImageFont.truetype("arial.ttf", 46)
        sub_font = ImageFont.truetype("arial.ttf", 28)
        text_font = ImageFont.truetype("arial.ttf", 24)
    except:
        title_font = sub_font = text_font = ImageFont.load_default()

    # Logo
    try:
        logo = Image.open(BytesIO(requests.get(LOGO_URL).content)).resize((120,120))
        img.paste(logo, (440, 20), logo if logo.mode=="RGBA" else None)
    except:
        pass

    invoice_id = f"PSG-{random.randint(10000,99999)}"
    date = time.strftime("%d / %m / %Y")

    draw.text((360, 150), "PSG FAMILY", fill=gold, font=title_font)
    draw.text((310, 200), "Official Premium Invoice", fill=gold, font=sub_font)

    y = 260
    row_h = 45
    for _ in range(7):
        draw.rectangle((80, y, 920, y+row_h), outline=gold, width=2)
        y += row_h

    draw.text((100, 270), f"Invoice ID: {invoice_id}", fill=white, font=text_font)
    draw.text((650, 270), f"Date: {date}", fill=white, font=text_font)
    draw.text((100, 315), f"Customer Name: {username}", fill=white, font=text_font)

    draw.text((100, 360), "Premium Details", fill=gold, font=sub_font)
    draw.text((100, 405), f"Premium Tier: {tier.capitalize()}", fill=white, font=text_font)
    draw.text((100, 450), f"Duration: {days} Days", fill=white, font=text_font)
    draw.text((100, 495), f"Coins Paid: {coins} PSG Coins", fill=white, font=text_font)

    draw.text((100, 540), "Payment Status:", fill=white, font=text_font)
    draw.text((320, 540), "PAID", fill=green, font=text_font)

    draw.text((600, 540), "Authorized By: PSG FAMILY", fill=white, font=text_font)
    draw.text((600, 580), "Signature: Kingofmyqueen", fill=gold, font=text_font)
    draw.text((360, 620), "Thank you for your support!", fill=gold, font=sub_font)

    buf = BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return buf


# ================= SELECT MENU =================
class TierSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Bronze (3 Days)", value="bronze", emoji="🥉"),
            discord.SelectOption(label="Silver (5 Days)", value="silver", emoji="🥈"),
            discord.SelectOption(label="Gold (7 Days)", value="gold", emoji="🥇"),
        ]
        super().__init__(
            placeholder="Select Premium Tier",
            options=options,
            custom_id="tier_select_menu"
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(BuyPremiumModal(self.values[0]))


# ================= BUY MODAL =================
class BuyPremiumModal(discord.ui.Modal):
    def __init__(self, tier):
        super().__init__(title="Buy Premium - PSG Family")
        self.tier = tier

        self.name = discord.ui.TextInput(label="Your Name")
        self.coupon = discord.ui.TextInput(
            label="Coupon Code (optional)",
            required=False,
            placeholder="Enter coupon code if any"
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
                return await interaction.response.send_message("❌ Invalid coupon code.", ephemeral=True)

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

        # ===== GENERATE INVOICE IMAGE =====
        invoice_img = generate_premium_invoice(
            interaction.user.name,
            tier,
            DAYS[tier],
            final_price
        )

        await interaction.response.send_message(
            content="🧾 **Premium Purchase Invoice**",
            file=discord.File(invoice_img, "premium_invoice.png"),
            ephemeral=True
        )

        try:
            await interaction.user.send(
                "🧾 **Your PSG Family Premium Invoice**",
                file=discord.File(invoice_img, "premium_invoice.png")
            )
        except:
            pass


# ================= VIEW =================
class CoinShopView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TierSelect())


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
                "🎟 Coupon supported (optional)\n"
                "Click below to buy premium."
            ),
            color=discord.Color.gold()
        )
        embed.set_thumbnail(url=LOGO_URL)

        await channel.send(embed=embed, view=CoinShopView())
        await interaction.response.send_message("✅ Coin shop panel created.", ephemeral=True)

    # ================= AUTO EXPIRY =================
    @tasks.loop(minutes=1)
    async def expiry_task(self):
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT user_id,tier,expires FROM premium") as cur:
                rows = await cur.fetchall()

        now = int(time.time())
        for user_id, tier, expires in rows:
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
