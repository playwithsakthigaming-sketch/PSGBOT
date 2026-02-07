import discord
import aiosqlite
import time
import asyncio
from discord.ext import commands
from discord import app_commands

DB_NAME = "bot.db"
TAX_PERCENT = 5


# ================= DATABASE SETUP =================
async def setup_database():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS shop_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            channel_id INTEGER
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS shop_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            price INTEGER,
            stock INTEGER,
            image_url TEXT,
            category_id INTEGER,
            product_link TEXT
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS coins (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER DEFAULT 0
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            item_name TEXT,
            total INTEGER,
            timestamp INTEGER
        )
        """)

        await db.commit()


# ================= PRODUCT EMBED =================
def product_embed(guild, item_id, name, price, stock, image_url, category):
    color = discord.Color.red() if stock <= 0 else discord.Color.green()

    desc = (
        f"📦 **Category:** {category}\n"
        f"💰 **Price:** {price} coins\n"
        f"📊 **Stock:** {stock}\n\n"
    )

    if stock <= 0:
        desc += "❌ **OUT OF STOCK**"
    else:
        desc += "Click **BUY** to purchase."

    embed = discord.Embed(title=name, description=desc, color=color)

    if image_url:
        embed.set_image(url=image_url)

    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    embed.set_footer(text=f"Item ID: {item_id}")
    return embed


# ================= PAYMENT CONFIRM VIEW =================
class PaymentConfirmView(discord.ui.View):
    def __init__(self, user_id, item_id, final_price, link, product_name):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.item_id = item_id
        self.final_price = final_price
        self.link = link
        self.product_name = product_name
        self.used = False

    @discord.ui.button(label="✅ Confirm Payment", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):

        if interaction.user.id != self.user_id:
            return await interaction.response.send_message(
                "❌ This payment is not for you.", ephemeral=True
            )

        if self.used:
            return await interaction.response.send_message(
                "⚠️ Payment already confirmed.", ephemeral=True
            )

        self.used = True
        await interaction.response.defer(ephemeral=True)

        try:
            async with aiosqlite.connect(DB_NAME) as db:
                cur = await db.execute(
                    "SELECT stock, product_link FROM shop_items WHERE id=?",
                    (self.item_id,)
                )
                row = await cur.fetchone()

                if not row or row[0] <= 0:
                    return await interaction.followup.send(
                        "❌ Item is out of stock.", ephemeral=True
                    )

                await db.execute(
                    "UPDATE coins SET balance = balance - ? WHERE user_id=?",
                    (self.final_price, interaction.user.id)
                )

                await db.execute(
                    "UPDATE shop_items SET stock = stock - 1 WHERE id=?",
                    (self.item_id,)
                )

                await db.execute("""
                INSERT INTO orders (user_id, item_name, total, timestamp)
                VALUES (?,?,?,?)
                """, (interaction.user.id, self.product_name, self.final_price, int(time.time())))

                await db.commit()

            try:
                await interaction.user.send(
                    f"🎉 Purchase Successful!\n"
                    f"📦 Product: {self.product_name}\n"
                    f"🔗 {self.link}"
                )
            except:
                pass

            await interaction.edit_original_response(
                content="✅ Purchase complete! Check your DM.",
                view=None
            )

        except Exception as e:
            await interaction.followup.send(
                f"❌ Error: {str(e)}", ephemeral=True
            )


# ================= BUY MODAL =================
class BuyModal(discord.ui.Modal, title="🛒 Purchase"):
    def __init__(self, item_id):
        super().__init__()
        self.item_id = item_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            async with aiosqlite.connect(DB_NAME) as db:
                cur = await db.execute(
                    "SELECT name, price, stock, product_link FROM shop_items WHERE id=?",
                    (self.item_id,)
                )
                item = await cur.fetchone()

                if not item:
                    return await interaction.followup.send("❌ Item not found.")

                name, price, stock, link = item

                if stock <= 0:
                    return await interaction.followup.send("❌ Out of stock.")

                tax = int(price * (TAX_PERCENT / 100))
                final_price = price + tax

                cur = await db.execute(
                    "SELECT balance FROM coins WHERE user_id=?",
                    (interaction.user.id,)
                )
                bal = await cur.fetchone()
                balance = bal[0] if bal else 0

                if balance < final_price:
                    return await interaction.followup.send(
                        f"❌ Not enough coins. Need {final_price}.",
                        ephemeral=True
                    )

            embed = discord.Embed(
                title="Payment",
                description=f"Total: {final_price} coins",
                color=discord.Color.gold()
            )

            view = PaymentConfirmView(
                interaction.user.id,
                self.item_id,
                final_price,
                link,
                name
            )

            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        except Exception as e:
            await interaction.followup.send(
                f"❌ Error: {str(e)}", ephemeral=True
            )


# ================= SHOP VIEW =================
class ShopView(discord.ui.View):
    def __init__(self, item_id, stock):
        super().__init__(timeout=None)
        self.item_id = item_id

        if stock <= 0:
            self.buy.disabled = True

    @discord.ui.button(label="🛒 BUY", style=discord.ButtonStyle.success)
    async def buy(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BuyModal(self.item_id))


# ================= SHOP COG =================
class Shop(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.loop.create_task(setup_database())

    # ---------- ADD CATEGORY ----------
    @app_commands.command(name="add_category")
    @app_commands.checks.has_permissions(administrator=True)
    async def add_category(self, interaction: discord.Interaction, name: str, channel: discord.TextChannel):
        await interaction.response.defer(ephemeral=True)

        try:
            async with aiosqlite.connect(DB_NAME) as db:
                await db.execute(
                    "INSERT OR REPLACE INTO shop_categories(name, channel_id) VALUES(?,?)",
                    (name, channel.id)
                )
                await db.commit()

            await interaction.followup.send(f"✅ Category `{name}` added.", ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

    # ---------- ADD PRODUCT ----------
    @app_commands.command(name="add_product")
    @app_commands.checks.has_permissions(administrator=True)
    async def add_product(self, interaction: discord.Interaction, name: str, price: int, stock: int, image_url: str, category: str, product_link: str):
        await interaction.response.defer(ephemeral=True)

        try:
            async with aiosqlite.connect(DB_NAME) as db:
                cur = await db.execute(
                    "SELECT id FROM shop_categories WHERE name=?",
                    (category,)
                )
                row = await cur.fetchone()

                if not row:
                    return await interaction.followup.send(
                        "❌ Category not found.",
                        ephemeral=True
                    )

                await db.execute("""
                INSERT INTO shop_items
                (name, price, stock, image_url, category_id, product_link)
                VALUES (?,?,?,?,?,?)
                """, (name, price, stock, image_url, row[0], product_link))

                await db.commit()

            await interaction.followup.send(f"✅ Product `{name}` added.", ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

    # ---------- SHOP ----------
    @app_commands.command(name="shop")
    async def shop(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            async with aiosqlite.connect(DB_NAME) as db:
                cur = await db.execute("""
                SELECT shop_items.id, shop_items.name, shop_items.price,
                       shop_items.stock, shop_items.image_url,
                       shop_categories.name, shop_categories.channel_id
                FROM shop_items
                JOIN shop_categories ON shop_items.category_id = shop_categories.id
                """)
                items = await cur.fetchall()

            if not items:
                return await interaction.followup.send("🛒 Shop empty", ephemeral=True)

            for item in items:
                item_id, name, price, stock, image_url, category_name, channel_id = item
                channel = interaction.guild.get_channel(channel_id)
                if not channel:
                    continue

                embed = product_embed(
                    interaction.guild,
                    item_id,
                    name,
                    price,
                    stock,
                    image_url,
                    category_name
                )
                await channel.send(embed=embed, view=ShopView(item_id, stock))

            await interaction.followup.send("🛒 Shop loaded.", ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)


# ================= SETUP =================
async def setup(bot: commands.Bot):
    await bot.add_cog(Shop(bot))
