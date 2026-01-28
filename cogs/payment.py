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

# ================= FONT =================
def get_font(size: int):
    if not os.path.exists(FONT_PATH):
        raise FileNotFoundError(f"Font not found: {FONT_PATH}")
    return ImageFont.truetype(FONT_PATH, size)

# ================= INVOICE CONFIG =================
SHOW_GRID = False

INVOICE_TEXT_CONFIG = {
    "invoice_id": {"x":152,"y":525,"fontSize":27},
    "date": {"x":675,"y":600,"fontSize":25},
    "customer": {"x":152,"y":668,"fontSize":23},
    "paid_amount": {"x":152,"y":725,"fontSize":22},
    "coin_credit": {"x":152,"y":600,"fontSize":28}
}

# ================= BACKGROUND =================
def load_invoice_background():
    W, H = 1080, 1080
    try:
        bg = Image.open(INVOICE_BG_PATH).convert("RGB")
        return bg.resize((W, H))
    except Exception as e:
        print("❌ BG load error:", e)
        return Image.new("RGB", (W, H), (30,30,30))

# ================= INVOICE GENERATOR =================
def generate_invoice(username, rupees, coins):
    img = load_invoice_background()
    draw = ImageDraw.Draw(img)

    if SHOW_GRID:
        for x in range(0,1000,50):
            draw.line((x,0,x,800),(60,60,60))
        for y in range(0,800,50):
            draw.line((0,y,1000,y),(60,60,60))

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
              fill="red")

    buf = BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return buf

# ================= PAYMENT PANEL VIEW =================
class PaymentPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="💰 Buy Coins", style=discord.ButtonStyle.success, custom_id="payment_buy")
    async def buy(self, interaction: discord.Interaction, _):
        guild = interaction.guild
        category = discord.utils.get(guild.categories, name=PAYMENT_CATEGORY)
        if not category:
            category = await guild.create_category(PAYMENT_CATEGORY)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True)
        }

        channel = await guild.create_text_channel(
            name=f"payment-{interaction.user.name}".lower(),
            category=category,
            overwrites=overwrites
        )

        embed = discord.Embed(
            title="💳 Payment Ticket",
            description=(
                f"{interaction.user.mention}\n\n"
                f"UPI ID: `{UPI_ID}`\n"
                f"₹{RUPEE_RATE} = {COINS_PER_RATE} PSG Coins\n\n"
                "📸 Upload payment screenshot.\n"
                "Admin will confirm."
            ),
            color=discord.Color.gold()
        )

        await channel.send(embed=embed, view=PaymentCloseView())
        await interaction.response.send_message(
            f"✅ Payment ticket created: {channel.mention}", ephemeral=True
        )

# ================= CLOSE VIEW =================
class PaymentCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 Close Ticket", style=discord.ButtonStyle.danger, custom_id="payment_close")
    async def close_ticket(self, interaction: discord.Interaction, _):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Admins only.", ephemeral=True)
        await interaction.channel.delete()

# ================= PAYMENT COG =================
class Payment(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="payment_panel")
    @app_commands.checks.has_permissions(administrator=True)
    async def payment_panel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="💳 Buy PSG Coins",
            description=f"₹{RUPEE_RATE} = {COINS_PER_RATE} PSG Coins\nClick below to buy.",
            color=discord.Color.gold()
        )
        embed.set_thumbnail(url=LOGO_URL)

        await interaction.channel.send(embed=embed, view=PaymentPanelView())
        await interaction.response.send_message("✅ Panel created.", ephemeral=True)

    @app_commands.command(name="confirm_payment")
    @app_commands.checks.has_permissions(administrator=True)
    async def confirm_payment(self, interaction: discord.Interaction, member: discord.Member, rupees: int):
        await interaction.response.defer(ephemeral=True)

        if rupees <= 0:
            return await interaction.followup.send("❌ Invalid amount.")

        coins = (rupees // RUPEE_RATE) * COINS_PER_RATE

        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("INSERT OR IGNORE INTO coins (user_id,balance) VALUES (?,0)", (member.id,))
            await db.execute("UPDATE coins SET balance = balance + ? WHERE user_id=?", (coins, member.id))
            await db.commit()

        invoice = generate_invoice(member.name, rupees, coins)

        await interaction.channel.send(file=discord.File(invoice, "invoice.png"))

        try:
            await member.send(file=discord.File(invoice, "invoice.png"))
        except:
            pass

        await interaction.followup.send(f"✅ Added {coins} coins to {member.mention}")

    @app_commands.command(name="invoice_preview")
    async def invoice_preview(self, interaction: discord.Interaction):
        img = generate_invoice(interaction.user.name, 100, 300)
        await interaction.response.send_message(
            file=discord.File(img, "preview.png"), ephemeral=True
        )

    @app_commands.command(name="invoice_edit")
    async def invoice_edit(self, interaction: discord.Interaction, field: str, x: int, y: int, size: int):
        if field not in INVOICE_TEXT_CONFIG:
            return await interaction.response.send_message("Invalid field", ephemeral=True)

        INVOICE_TEXT_CONFIG[field]["x"] = x
        INVOICE_TEXT_CONFIG[field]["y"] = y
        INVOICE_TEXT_CONFIG[field]["fontSize"] = size

        await interaction.response.send_message(
            f"✅ {field} updated to x={x}, y={y}, size={size}", ephemeral=True
        )

    @app_commands.command(name="invoice_grid")
    async def invoice_grid(self, interaction: discord.Interaction, show: bool):
        global SHOW_GRID
        SHOW_GRID = show
        await interaction.response.send_message(f"Grid = {show}", ephemeral=True)

# ================= SETUP =================
async def setup(bot: commands.Bot):
    bot.add_view(PaymentPanelView())
    bot.add_view(PaymentCloseView())
    await bot.add_cog(Payment(bot))
