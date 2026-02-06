import discord
import aiosqlite
from discord.ext import commands
from discord import app_commands
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO

DB_NAME = "bot.db"

# ================= CONFIG =================
XP_PER_MESSAGE = 10
COINS_PER_LEVEL = 20

# Only this channel gives XP
LEVEL_CHANNEL_ID = 123456789012345678  # <-- CHANGE THIS


# ================= LEVEL FORMULA =================
def xp_needed(level: int):
    return 100 + (level * 50)


# ================= RANK CARD =================
def generate_rank_card(username, avatar_bytes, level, xp, needed, coins):
    W, H = 900, 300
    img = Image.new("RGB", (W, H), (20, 20, 20))
    draw = ImageDraw.Draw(img)

    # Fonts
    try:
        name_font = ImageFont.truetype("fonts/CinzelDecorative-Bold.ttf", 50)
        level_font = ImageFont.truetype("fonts/CinzelDecorative-Bold.ttf", 36)
        small_font = ImageFont.truetype("fonts/CinzelDecorative-Bold.ttf", 26)
    except:
        name_font = level_font = small_font = ImageFont.load_default()

    # Avatar
    avatar = Image.open(BytesIO(avatar_bytes)).resize((150, 150)).convert("RGBA")
    img.paste(avatar, (30, 75), avatar)

    # Text
    draw.text((220, 40), username, font=name_font, fill="white")
    draw.text((220, 120), f"LEVEL {level}", font=level_font, fill="gold")
    draw.text((220, 155), f"+{coins} COINS", font=level_font, fill=(0, 255, 200))

    # XP text
    draw.text((220, 210), f"XP: {xp} / {needed}", font=small_font, fill="white")

    # XP BAR
    bar_x = 220
    bar_y = 250
    bar_w = 600
    bar_h = 25

    progress = int((xp / needed) * bar_w)

    draw.rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), fill=(60, 60, 60))
    draw.rectangle((bar_x, bar_y, bar_x + progress, bar_y + bar_h), fill=(0, 200, 255))

    buf = BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return buf


# ================= LEVEL COG =================
class Levels(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ---------------- XP LISTENER ----------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        # Only allow XP in one channel
        if message.channel.id != LEVEL_CHANNEL_ID:
            return

        user_id = message.author.id
        guild_id = message.guild.id

        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute(
                "SELECT xp, level FROM levels WHERE user_id=? AND guild_id=?",
                (user_id, guild_id)
            )
            row = await cur.fetchone()

            if not row:
                xp = 0
                level = 1
                await db.execute(
                    "INSERT INTO levels (user_id, guild_id, xp, level) VALUES (?,?,?,?)",
                    (user_id, guild_id, xp, level)
                )
            else:
                xp, level = row

            xp += XP_PER_MESSAGE
            coins = 0

            # MULTI LEVEL SYSTEM
            while xp >= xp_needed(level):
                xp -= xp_needed(level)
                level += 1
                coins += level * COINS_PER_LEVEL

            # Save level data
            await db.execute(
                "UPDATE levels SET xp=?, level=? WHERE user_id=? AND guild_id=?",
                (xp, level, user_id, guild_id)
            )

            # Reward coins
            if coins > 0:
                await db.execute(
                    "INSERT OR IGNORE INTO coins (user_id, balance) VALUES (?,0)",
                    (user_id,)
                )
                await db.execute(
                    "UPDATE coins SET balance = balance + ? WHERE user_id=?",
                    (coins, user_id)
                )

            await db.commit()

        # Send level-up card
        if coins > 0:
            await self.send_rank_card(message, level, xp, coins)

    # ---------------- RANK CARD SEND ----------------
    async def send_rank_card(self, message, level, xp, coins):
        avatar = await message.author.display_avatar.read()
        needed = xp_needed(level)

        card = generate_rank_card(
            message.author.name,
            avatar,
            level,
            xp,
            needed,
            coins
        )

        await message.channel.send(
            content=f"🎉 {message.author.mention} leveled up!",
            file=discord.File(card, "rank.png")
        )

    # ---------------- /LEVEL ----------------
    @app_commands.command(name="level", description="Check your level")
    async def level_cmd(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        user_id = member.id
        guild_id = interaction.guild.id

        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute(
                "SELECT xp, level FROM levels WHERE user_id=? AND guild_id=?",
                (user_id, guild_id)
            )
            row = await cur.fetchone()

        if not row:
            return await interaction.response.send_message("No level data yet.", ephemeral=True)

        xp, level = row
        needed = xp_needed(level)

        avatar = await member.display_avatar.read()
        card = generate_rank_card(member.name, avatar, level, xp, needed, 0)

        await interaction.response.send_message(
            file=discord.File(card, "rank.png")
        )

    # ---------------- /ADDXP ----------------
    @app_commands.command(name="addxp", description="Admin: Add XP to a user")
    @app_commands.checks.has_permissions(administrator=True)
    async def addxp(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        user_id = member.id
        guild_id = interaction.guild.id

        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute(
                "SELECT xp, level FROM levels WHERE user_id=? AND guild_id=?",
                (user_id, guild_id)
            )
            row = await cur.fetchone()

            if not row:
                xp = 0
                level = 1
            else:
                xp, level = row

            xp += amount
            coins = 0

            while xp >= xp_needed(level):
                xp -= xp_needed(level)
                level += 1
                coins += level * COINS_PER_LEVEL

            await db.execute(
                "INSERT OR REPLACE INTO levels (user_id, guild_id, xp, level) VALUES (?,?,?,?)",
                (user_id, guild_id, xp, level)
            )

            if coins > 0:
                await db.execute(
                    "INSERT OR IGNORE INTO coins (user_id, balance) VALUES (?,0)",
                    (user_id,)
                )
                await db.execute(
                    "UPDATE coins SET balance = balance + ? WHERE user_id=?",
                    (coins, user_id)
                )

            await db.commit()

        await interaction.response.send_message(
            f"✅ Added {amount} XP to {member.mention}"
        )


# ================= SETUP =================
async def setup(bot: commands.Bot):
    await bot.add_cog(Levels(bot))
