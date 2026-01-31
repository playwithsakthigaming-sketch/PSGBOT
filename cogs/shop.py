import discord, aiosqlite, time
from discord.ext import commands
from discord import app_commands

DB_NAME = "bot.db"
TAX_PERCENT = 5


# ================= PRODUCT EMBED =================
def product_embed(item_id, name, price, stock, image_url, category):
    embed = discord.Embed(
        title=name,
        description=(
            f"📦 Category: **{category}**\n"
            f"💰 Price: **{price} coins**\n"
            f"📊 Stock: **{stock}**\n\n"
            "Click BUY to purchase"
        ),
        color=discord.Color.purple()
    )
    if image_url:
        embed.set_image(url=image_url)
    embed.set_footer(text=f"Item ID: {item_id}")
    return embed


# ================= BUY BUTTON =================
class BuyView(discord.ui.View):
    def __init__(self, item_id):
        super().__init__(timeout=None)
        self.item_id = item_id

    @discord.ui.button(label="🛒 BUY", style=discord.ButtonStyle.success)
    async def buy(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CheckoutForm(self.item_id))


# ================= CHECKOUT MODAL =================
class CheckoutForm(discord.ui.Modal, title="🧾 Checkout"):
    name = discord.ui.TextInput(label="Your Name", required=True)
    gmail = discord.ui.TextInput(label="Gmail", required=True)
    coupon = discord.ui.TextInput(label="Coupon (optional)", required=False)

    def __init__(self, item_id):
        super().__init__()
        self.item_id = item_id

    async def on_submit(self, interaction: discord.Interaction):

        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute(
                "SELECT name, price FROM shop_items WHERE id=?",
                (self.item_id,)
            )
            item = await cur.fetchone()

            if not item:
                return await interaction.response.send_message("❌ Item not found", ephemeral=True)

            item_name, price = item

            discount = 0
            if self.coupon.value:
                cur = await db.execute(
                    "SELECT value, used, max_uses FROM coupons WHERE code=?",
                    (self.coupon.value,)
                )
                row = await cur.fetchone()
                if row and row[1] < row[2]:
                    discount = row[0]

            tax = int(price * TAX_PERCENT / 100)
            total = price + tax - discount

        embed = discord.Embed(
            title="💳 Payment Details",
            description=(
                f"👤 Name: {self.name.value}\n"
                f"📧 Gmail: {self.gmail.value}\n\n"
                f"🛒 Item: {item_name}\n"
                f"💰 Price: {price} coins\n"
                f"🧾 Tax ({TAX_PERCENT}%): {tax}\n"
                f"🎟 Discount: {discount}\n\n"
                f"✅ **Total: {total} coins**"
            ),
            color=discord.Color.gold()
        )

        await interaction.response.send_message(
            embed=embed,
            view=ConfirmPaymentView(self.item_id, total),
            ephemeral=True
        )


# ================= CONFIRM PAYMENT =================
class ConfirmPaymentView(discord.ui.View):
    def __init__(self, item_id, total):
        super().__init__(timeout=None)
        self.item_id = item_id
        self.total = total

    @discord.ui.button(label="✅ Confirm Payment", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):

        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute(
                "SELECT balance FROM coins WHERE user_id=?",
                (interaction.user.id,)
            )
            row = await cur.fetchone()
            balance = row[0] if row else 0

            if balance < self.total:
                return await interaction.response.send_message(
                    "❌ Not enough coins", ephemeral=True
                )

            await db.execute(
                "UPDATE coins SET balance = balance - ? WHERE user_id=?",
                (self.total, interaction.user.id)
            )

            await db.execute("""
            INSERT INTO orders (user_id, total, timestamp)
            VALUES (?,?,?)
            """, (interaction.user.id, self.total, int(time.time())))

            await db.commit()

        await interaction.response.send_message(
            "✅ Payment successful! Order placed.", ephemeral=True
        )


# ================= SHOP COG =================
class Shop(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # -------- ADD CATEGORY --------
    @app_commands.command(name="category_add")
    @app_commands.checks.has_permissions(administrator=True)
    async def category_add(self, interaction: discord.Interaction, name: str):
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "INSERT OR IGNORE INTO shop_categories (name) VALUES (?)",
                (name,)
            )
            await db.commit()

        await interaction.response.send_message(f"✅ Category `{name}` added")

    # -------- ADD ITEM --------
    @app_commands.command(name="shop_add")
    @app_commands.checks.has_permissions(administrator=True)
    async def shop_add(
        self,
        interaction: discord.Interaction,
        name: str,
        price: int,
        stock: int,
        image_url: str,
        category: str
    ):
        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute(
                "SELECT id FROM shop_categories WHERE name=?",
                (category,)
            )
            row = await cur.fetchone()

            if not row:
                return await interaction.response.send_message("❌ Category not found")

            category_id = row[0]

            await db.execute("""
            INSERT INTO shop_items (name, price, stock, image_url, category_id)
            VALUES (?,?,?,?,?)
            """, (name, price, stock, image_url, category_id))

            await db.commit()

        await interaction.response.send_message(f"✅ Item `{name}` added")

    # -------- SHOW SHOP --------
    @app_commands.command(name="shop")
    async def shop(self, interaction: discord.Interaction):

        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute("""
            SELECT shop_items.id, shop_items.name, shop_items.price,
                   shop_items.stock, shop_items.image_url,
                   shop_categories.name
            FROM shop_items
            JOIN shop_categories ON shop_items.category_id = shop_categories.id
            """)
            items = await cur.fetchall()

        if not items:
            return await interaction.response.send_message("🛒 Shop is empty")

        for item_id, name, price, stock, image_url, category in items:
            embed = product_embed(item_id, name, price, stock, image_url, category)
            view = BuyView(item_id)
            await interaction.channel.send(embed=embed, view=view)

        await interaction.response.send_message("✅ Shop loaded", ephemeral=True)

    # -------- ORDER HISTORY --------
    @app_commands.command(name="order_history")
    async def order_history(self, interaction: discord.Interaction):
        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute(
                "SELECT total, timestamp FROM orders WHERE user_id=?",
                (interaction.user.id,)
            )
            rows = await cur.fetchall()

        if not rows:
            return await interaction.response.send_message("❌ No orders found")

        embed = discord.Embed(title="📜 Order History", color=discord.Color.blue())

        for total, ts in rows:
            embed.add_field(
                name="Order",
                value=f"💰 {total} coins\n🕒 <t:{ts}:R>",
                inline=False
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)


# ================= SETUP =================
async def setup(bot: commands.Bot):
    await bot.add_cog(Shop(bot))
