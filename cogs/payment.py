import discord
import aiosqlite
import time
import random
import os
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from discord.ext import commands
from discord import app_commands

DB_NAME = "bot.db"

# ================= CONFIG =================
UPI_ID = "psgfamily@upi"
RUPEE_RATE = 2
COINS_PER_RATE = 6

LOGO_URL = "https://cdn.discordapp.com/attachments/1415142396341256275/1463808464840294463/1000068286-removebg-preview.png"

PAYMENT_CATEGORY = "Payments"

INVOICE_BG_PATH = "assets/invoice_bg.png"
FONT_PATH = "fonts/CinzelDecorative-Bold.ttf"

# ================= COUPONS =================
COUPONS = {
    "PSG10": {"bonus_coins": 10},
    "FREE5": {"bonus_coins": 5},
    "VIP50": {"bonus_coins": 50}
}

# ================= FONT =================
def get_font(size: int):
    if not os.path.exists(FONT_PATH):
        return ImageFont.load_default()
    return ImageFont.truetype(FONT_PATH, size)

# ================= INVOICE CONFIG =================
INVOICE_TEXT_CONFIG = {
    "invoice_id": {"x":152,"y":525,"fontSize":25},
    "date": {"x":675,"y":525,"fontSize":25},
    "customer": {"x":152,"y":600,"fontSize":23},
    "paid_amount": {"x":152,"y":730,"fontSize":22},
    "coin_credit": {"x":152,"y":670,"fontSize":22}
}

# ================= BACKGROUND =================
def load_invoice_background():
    W, H = 1080, 1080
    try:
        bg = Image.open(INVOICE_BG_PATH).convert("RGB")
        return bg.resize((W, H))
    except:
        return Image.new("RGB", (W, H), (30,30,30))

# ================= INVOICE GENERATOR =================
def generate_invoice(username, rupees, coins):
    img = load_invoice_background()
    draw = ImageDraw.Draw(img)

    invoice_id = f"PSG-{random.randint(10000,99999)}"
    date = time.strftime("%d/%m/%Y")

    cfg = INVOICE_TEXT_CONFIG

    draw.text((cfg["invoice_id"]["x"], cfg["invoice_id"]["y"]),
              f"Invoice ID: {invoice_id}",
              font=get_font(cfg["invoice_id"]["fontSize"]),
              fill="gold")

    draw.text((cfg["date"]["x"], cfg["date"]["y"]),
              f"Date: {date}",
              font=get_font(cfg["date"]["fontSize"]),
              fill="white")

    draw.text((cfg["customer"]["x"], cfg["customer"]["y"]),
              f"Customer: {username}",
              font=get_font(cfg["customer"]["fontSize"]),
              fill="white")

    draw.text((cfg["paid_amount"]["x"], cfg["paid_amount"]["y"]),
              f"Paid Amount: ₹{rupees}",
              font=get_font(cfg["paid_amount"]["fontSize"]),
              fill="white")

    draw.text((cfg["coin_credit"]["x"], cfg["coin_credit"]["y"]),
              f"Coins Credited: {coins}",
              font=get_font(cfg["coin_credit"]["fontSize"]),
              fill="cyan")

    buf = BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return buf

# ================= BUY COINS MODAL =================
class BuyCoinsModal(discord.ui.Modal, title="Buy PSG Coins"):
    name = discord.ui.TextInput(label="Your Name", placeholder="Enter your name", required=True)
    coupon = discord.ui.TextInput(label="Coupon Code (optional)", placeholder="Enter coupon code", required=False)

    def __init__(self, user):
        super().__init__()
        self.user = user

    async def on_submit(self, interaction: discord.Interaction):

        coupon_code = self.coupon.value.strip().upper() if self.coupon.value else None

        # ===== COUPON VERIFY =====
        bonus_coins = 0
        if coupon_code:
            if coupon_code not in COUPONS:
                return await interaction.response.send_message(
                    "❌ Invalid coupon code. Ticket not created.",
                    ephemeral=True
                )
            else:
                bonus_coins = COUPONS[coupon_code]["bonus_coins"]

        guild = interaction.guild

        category = discord.utils.get(guild.categories, name=PAYMENT_CATEGORY)
        if not category:
            category = await guild.create_category(PAYMENT_CATEGORY)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            self.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(view_channel=True),
        }

        channel = await guild.create_text_channel(
            name=f"payment-{self.user.name}".lower(),
            category=category,
            overwrites=overwrites
        )

        embed = discord.Embed(
            title="💳 Payment Ticket",
            description=(
                f"👤 **Name:** {self.name.value}\n"
                f"🎟 **Coupon Code:** {coupon_code if coupon_code else 'None'}\n"
                f"🎁 **Bonus Coins:** {bonus_coins}\n\n"
                f"**UPI ID:** `{UPI_ID}`\n"
                f"**Rate:** ₹{RUPEE_RATE} = {COINS_PER_RATE} PSG Coins\n\n"
                "📸 Upload your payment screenshot here.\n"
                "Admin will confirm your payment."
            ),
            color=discord.Color.gold()
        )

        await channel.send(embed=embed, view=PaymentCloseView())

        await interaction.response.send_message(
            f"✅ Payment ticket created: {channel.mention}",
            ephemeral=True
        )

# ================= PAYMENT PANEL VIEW =================
class PaymentPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="💰 Buy Coins", style=discord.ButtonStyle.success, custom_id="payment_buy")
    async def buy(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BuyCoinsModal(interaction.user))

# ================= CLOSE VIEW =================
class PaymentCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 Close Ticket", style=discord.ButtonStyle.danger, custom_id="payment_close")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admins only.", ephemeral=True)

        await interaction.channel.delete()

# ================= PAYMENT COG =================
class Payment(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # -------- PANEL --------
    @app_commands.command(name="payment_panel")
    @app_commands.checks.has_permissions(administrator=True)
    async def payment_panel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="💳 Buy PSG Coins",
            description=f"₹{RUPEE_RATE} = {COINS_PER_RATE} PSG Coins\n\nClick below to buy.",
            color=discord.Color.gold()
        )
        embed.set_thumbnail(url=LOGO_URL)

        await interaction.channel.send(embed=embed, view=PaymentPanelView())
        await interaction.response.send_message("✅ Payment panel created.", ephemeral=True)

    # -------- CONFIRM PAYMENT --------
    @app_commands.command(name="confirm_payment")
    @app_commands.checks.has_permissions(administrator=True)
    async def confirm_payment(self, interaction: discord.Interaction, member: discord.Member, rupees: int):
        await interaction.response.defer(ephemeral=True)

        if rupees <= 0:
            return await interaction.followup.send("❌ Invalid amount.")

        base_coins = (rupees // RUPEE_RATE) * COINS_PER_RATE
        bonus = 0

        async for msg in interaction.channel.history(limit=10):
            if msg.embeds:
                emb = msg.embeds[0]
                if "Bonus Coins" in emb.description:
                    for line in emb.description.split("\n"):
                        if "Bonus Coins" in line:
                            bonus = int(line.split(":")[1].strip())
                    break

        total_coins = base_coins + bonus

        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "INSERT OR IGNORE INTO coins (user_id,balance) VALUES (?,0)",
                (member.id,)
            )
            await db.execute(
                "UPDATE coins SET balance = balance + ? WHERE user_id=?",
                (total_coins, member.id)
            )
            await db.commit()

        invoice = generate_invoice(member.name, rupees, total_coins)

        await interaction.channel.send(file=discord.File(invoice, "invoice.png"))

        await interaction.followup.send(
            f"✅ Added **{total_coins} coins** to {member.mention}"
        )

# ================= SETUP =================
async def setup(bot: commands.Bot):
    bot.add_view(PaymentPanelView())
    bot.add_view(PaymentCloseView())
    await bot.add_cog(Payment(bot))
