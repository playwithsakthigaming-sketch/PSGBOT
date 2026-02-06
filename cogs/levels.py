import discord
import aiosqlite
import time
import requests
from discord.ext import commands
from discord import app_commands
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import os

DB_NAME = "bot.db"

# ================= CONFIG =================
LEVEL_CHANNEL_ID = 1465720466420269121  # ← PUT YOUR LEVEL CHANNEL ID HERE
CARD_BG_URL = "https://files.catbox.moe/yslxzu.png"
FONT_PATH = "fonts/CinzelDecorative-Bold.ttf"

XP_PER_MESSAGE = 15
COINS_PER_LEVEL = 20
COOLDOWN = 10  # seconds


# ================= FONT =================
def get_font(size: int):
    return ImageFont.truetype(FONT_PATH, size)


# ================= XP FORMULA =================
def xp_needed(level: int):
    return 100 + (level * 50)


# ================= RANK CARD =================
async def generate_rank_card(member, level, xp, coins):
    try:
        r = requests.get(CARD_BG_URL, timeout=10)
        bg = Image.open(BytesIO(r.content)).convert("RGB")
    except:
        bg = Image.new("RGB", (900, 300), (30, 30, 30))

    bg = bg.resize((900, 300))
    draw = ImageDraw.Draw(bg)

    # Avatar
    try:
        avatar_bytes = await member.display_avatar.read()
        avatar = Image.open(BytesIO(avatar_bytes)).resize((180, 180)).convert("RGBA")
        bg.paste(avatar, (40, 60), avatar)
    except:
        pass

    # Fonts
    font_big = get_font(42)
    font_mid = get_font(28)
    font_small = get_font(24)

    # Text
    draw.text((250, 60), member.name.upper(), font=font_big, fill="white")
    draw.text((250, 120), f"LEVEL {level}", font=font_mid, fill="gold")
    draw.text((250, 170), f"+{coins} COINS", font=font_mid, fill="cyan")

    # XP BAR
    needed = xp_needed(level)
    progress = min(xp / needed, 1.0)

    bar_x = 250
    bar_y = 220
    bar_width = 500
    bar_height = 25

    # Background
    draw.rectangle(
        (bar_x, bar_y, bar_x + bar_width, bar_y + bar_height),
        fill=(60, 60, 60)
    )

    # Progress
    draw.rectangle(
        (
            bar_x,
            bar_y,
            bar_x + int(bar_width * progress),
            bar_y + bar_height
        ),
        fill=(0, 200, 255)
    )

    # XP text
    draw.text(
        (bar_x, bar_y - 30),
        f"XP: {xp} / {needed}",
        font=font_small,
        fill="white"
    )

    buf = BytesIO()
    bg.save(buf, "PNG")
    buf.seek(0)
    return buf


# ================= COG =================
class Levels(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.cooldowns = {}

    # ================= MESSAGE XP =================
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        if message.channel.id != LEVEL_CHANNEL_ID:
            return

        user_id = message.author.id
        guild_id = message.guild.id

        now = time.time()
        if user_id in self.cooldowns:
            if now - self.cooldowns[user_id] < COOLDOWN:
                return

        self.cooldowns[user_id] = now

        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("""
                INSERT OR IGNORE INTO levels (user_id, guild_id, xp, level)
                VALUES (?, ?, 0, 1)
            """, (user_id, guild_id))

            cur = await db.execute("""
                SELECT xp, level FROM levels
                WHERE user_id=? AND guild_id=?
            """, (user_id, guild_id))
            row = await cur.fetchone()

            xp, level = row
            xp += XP_PER_MESSAGE

            needed = xp_needed(level)

            if xp >= needed:
                level += 1
                xp = 0
                coins = level * COINS_PER_LEVEL

                # add coins
                await db.execute(
                    "INSERT OR IGNORE INTO coins (user_id, balance) VALUES (?,0)",
                    (user_id,)
                )
                await db.execute(
                    "UPDATE coins SET balance = balance + ? WHERE user_id=?",
                    (coins, user_id)
                )

                await self.send_rank_card(message, level, xp, coins)

            await db.execute("""
                UPDATE levels
                SET xp=?, level=?
                WHERE user_id=? AND guild_id=?
            """, (xp, level, user_id, guild_id))

            await db.commit()

    # ================= SEND CARD =================
    async def send_rank_card(self, message, level, xp, coins):
        card = await generate_rank_card(message.author, level, xp, coins)

        await message.channel.send(
            content=f"🎉 {message.author.mention} leveled up!",
            file=discord.File(card, "rank.png")
        )

    # ================= /LEVEL =================
    @app_commands.command(name="level", description="View your level")
    async def level_cmd(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user

        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute("""
                SELECT xp, level FROM levels
                WHERE user_id=? AND guild_id=?
            """, (member.id, interaction.guild.id))
            row = await cur.fetchone()

            if not row:
                return await interaction.response.send_message(
                    "No level data.",
                    ephemeral=True
                )

            xp, level = row

            cur = await db.execute(
                "SELECT balance FROM coins WHERE user_id=?",
                (member.id,)
            )
            coin_row = await cur.fetchone()
            coins = coin_row[0] if coin_row else 0

        card = await generate_rank_card(member, level, xp, coins)

        await interaction.response.send_message(
            file=discord.File(card, "rank.png")
        )

    # ================= /ADDXP =================
    @app_commands.command(name="addxp", description="Add XP to a user")
    @app_commands.checks.has_permissions(administrator=True)
    async def addxp(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        amount: int
    ):
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("""
                INSERT OR IGNORE INTO levels (user_id, guild_id, xp, level)
                VALUES (?, ?, 0, 1)
            """, (member.id, interaction.guild.id))

            await db.execute("""
                UPDATE levels
                SET xp = xp + ?
                WHERE user_id=? AND guild_id=?
            """, (amount, member.id, interaction.guild.id))

            await db.commit()

        await interaction.response.send_message(
            f"✅ Added {amount} XP to {member.mention}",
            ephemeral=True
        )


# ================= SETUP =================
async def setup(bot: commands.Bot):
    await bot.add_cog(Levels(bot))
