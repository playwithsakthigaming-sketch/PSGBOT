import discord
import time, random, aiosqlite, requests, json, os
from discord.ext import commands, tasks
from discord import app_commands
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

DB_NAME = "bot.db"
POS_FILE = "invoice_positions.json"

# ================= CONFIG =================
PRICES = {"bronze": 100, "silver": 200, "gold": 300}
DAYS = {"bronze": 3, "silver": 5, "gold": 7}

PREMIUM_ROLE_IDS = {
    "bronze": 1463834717987274814,
    "silver": 1463884119032463433,
    "gold": 1463884209025187880
}

INVOICE_BG = "https://files.catbox.moe/ah29yy.png"


# ================= POSITION SYSTEM =================
default_positions = {
    "date": [700, 260],
    "invoice_id": [250, 320],
    "customer": [300, 380],
    "tier": [250, 440],
    "days": [250, 500],
    "paid": [350, 560]
}

def load_positions():
    if not os.path.exists(POS_FILE):
        with open(POS_FILE, "w") as f:
            json.dump(default_positions, f, indent=4)
        return default_positions
    with open(POS_FILE) as f:
        return json.load(f)

def save_positions(data):
    with open(POS_FILE, "w") as f:
        json.dump(data, f, indent=4)


# ================= PREMIUM INVOICE IMAGE =================
def generate_premium_invoice(username: str, tier: str, days: int, coins: int):
    pos = load_positions()

    try:
        bg = Image.open(BytesIO(requests.get(INVOICE_BG).content)).convert("RGB")
        img = bg.resize((1000, 650))
    except:
        img = Image.new("RGB", (1000, 650), (10, 10, 10))

    draw = ImageDraw.Draw(img)
    white = (255, 255, 255)
    green = (0, 255, 0)

    try:
        text_font = ImageFont.truetype("arial.ttf", 32)
    except:
        text_font = ImageFont.load_default()

    invoice_id = f"PSG-{random.randint(10000,99999)}"
    date = time.strftime("%d / %m / %Y")

    draw.text(tuple(pos["date"]), date, fill=white, font=text_font)
    draw.text(tuple(pos["invoice_id"]), invoice_id, fill=white, font=text_font)
    draw.text(tuple(pos["customer"]), username, fill=white, font=text_font)
    draw.text(tuple(pos["tier"]), tier.capitalize(), fill=white, font=text_font)
    draw.text(tuple(pos["days"]), f"{days} Days", fill=white, font=text_font)
    draw.text(tuple(pos["paid"]), "PAID", fill=green, font=text_font)

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
        self.add_item(self.name)

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        tier = self.tier
        final_price = PRICES[tier]

        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "INSERT OR REPLACE INTO premium (user_id,tier,expires) VALUES (?,?,?)",
                (user_id, tier, int(time.time()) + DAYS[tier] * 86400)
            )
            await db.commit()

        role = interaction.guild.get_role(PREMIUM_ROLE_IDS[tier])
        if role:
            await interaction.user.add_roles(role)

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


# ================= VIEW =================
class CoinShopView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TierSelect())


# ================= COG =================
class CoinShop(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ---------- Invoice Preview ----------
    @app_commands.command(name="invoice_preview", description="Preview premium invoice")
    async def invoice_preview(self, interaction: discord.Interaction, user: discord.Member, tier: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

        tier = tier.lower()
        if tier not in PRICES:
            return await interaction.response.send_message("Invalid tier.", ephemeral=True)

        img = generate_premium_invoice(user.name, tier, DAYS[tier], PRICES[tier])
        await interaction.response.send_message(file=discord.File(img, "preview.png"))

    # ---------- Invoice Position Edit ----------
    @app_commands.command(name="invoice_edit", description="Edit invoice text position")
    async def invoice_edit(self, interaction: discord.Interaction, field: str, x: int, y: int):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

        pos = load_positions()

        if field not in pos:
            return await interaction.response.send_message(
                "Invalid field. Options: date, invoice_id, customer, tier, days, paid",
                ephemeral=True
            )

        pos[field] = [x, y]
        save_positions(pos)

        await interaction.response.send_message(
            f"✅ Updated **{field}** position to ({x}, {y})",
            ephemeral=True
        )


# ================= SETUP =================
async def setup(bot):
    bot.add_view(CoinShopView())
    await bot.add_cog(CoinShop(bot))
