import discord
import aiosqlite
import random
import time
import os
from discord.ext import commands
from discord import app_commands
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import requests

DB_NAME = "bot.db"
XP_PER_MESSAGE = (5, 15)

FONT_PATH = "fonts/CinzelDecorative-Bold.ttf"
CARD_BG_URL = "https://files.catbox.moe/yslxzu.png"


# ================= XP FORMULA =================
def xp_needed(level: int):
    return 100 + (level * 50)


# ================= SAFE FONT =================
def get_font(size):
    try:
        if os.path.exists(FONT_PATH):
            return ImageFont.truetype(FONT_PATH, size)
    except:
        pass
    return ImageFont.load_default()


# ================= RANK CARD =================
async def generate_rank_card(member, level, coins):
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

    font_big = get_font(40)
    font_small = get_font(25)

    draw.text((250, 80), member.name, font=font_big, fill="white")
    draw.text((250, 150), f"Level {level}", font=font_small, fill="gold")
    draw.text((250, 200), f"+{coins} coins", font=font_small, fill="cyan")

    buf = BytesIO()
    bg.save(buf, "PNG")
    buf.seek(0)
    return buf


# ================= LEVEL COG =================
class Levels(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.cooldowns = {}

    # ---------------- MESSAGE XP ----------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        user_id = message.author.id
        guild_id = message.guild.id
        now = time.time()

        # 10 second cooldown
        if user_id in self.cooldowns:
            if now - self.cooldowns[user_id] < 10:
                return

        self.cooldowns[user_id] = now
        xp_gain = random.randint(*XP_PER_MESSAGE)

        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute(
                "SELECT xp, level FROM levels WHERE user_id=? AND guild_id=?",
                (user_id, guild_id)
            )
            row = await cur.fetchone()

            if not row:
                xp = xp_gain
                level = 1
                await db.execute(
                    "INSERT INTO levels (user_id, guild_id, xp, level) VALUES (?,?,?,?)",
                    (user_id, guild_id, xp, level)
                )
            else:
                xp, level = row
                xp += xp_gain

                needed = xp_needed(level)
                if xp >= needed:
                    level += 1
                    xp -= needed

                    # Coin reward
                    coins = 20
                    if level % 5 == 0:
                        coins += 50

                    await db.execute(
                        "INSERT OR IGNORE INTO coins (user_id, balance) VALUES (?,0)",
                        (user_id,)
                    )
                    await db.execute(
                        "UPDATE coins SET balance = balance + ? WHERE user_id=?",
                        (coins, user_id)
                    )

                    await db.commit()

                    # Send rank card
                    await self.send_rank_card(message, level, coins)

                await db.execute(
                    "UPDATE levels SET xp=?, level=? WHERE user_id=? AND guild_id=?",
                    (xp, level, user_id, guild_id)
                )

            await db.commit()

    # ---------------- SEND RANK CARD ----------------
    async def send_rank_card(self, message, level, coins):
        card = await generate_rank_card(message.author, level, coins)

        await message.channel.send(
            content=f"🎉 {message.author.mention} leveled up!",
            file=discord.File(card, "rank.png")
        )

    # ---------------- /LEVEL COMMAND ----------------
    @app_commands.command(name="level", description="View your rank card")
    async def level_cmd(self, interaction: discord.Interaction, member: discord.Member = None):
        await interaction.response.defer()

        try:
            if member is None:
                member = interaction.user

            async with aiosqlite.connect(DB_NAME) as db:
                cur = await db.execute(
                    "SELECT level FROM levels WHERE user_id=? AND guild_id=?",
                    (member.id, interaction.guild.id)
                )
                row = await cur.fetchone()
                level = row[0] if row else 1

                cur = await db.execute(
                    "SELECT balance FROM coins WHERE user_id=?",
                    (member.id,)
                )
                row = await cur.fetchone()
                coins = row[0] if row else 0

            card = await generate_rank_card(member, level, coins)

            await interaction.followup.send(
                file=discord.File(card, "rank.png")
            )

        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}")

    # ---------------- ADMIN ADD LEVEL ----------------
    @app_commands.command(name="addlevel", description="Admin: Add levels to a user")
    @app_commands.checks.has_permissions(administrator=True)
    async def addlevel(self, interaction: discord.Interaction, member: discord.Member, levels: int):
        await interaction.response.defer(ephemeral=True)

        if levels <= 0:
            return await interaction.followup.send("❌ Levels must be positive.")

        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute(
                "SELECT level FROM levels WHERE user_id=? AND guild_id=?",
                (member.id, interaction.guild.id)
            )
            row = await cur.fetchone()

            if not row:
                new_level = levels
                await db.execute(
                    "INSERT INTO levels (user_id, guild_id, xp, level) VALUES (?,?,0,?)",
                    (member.id, interaction.guild.id, new_level)
                )
            else:
                current_level = row[0]
                new_level = current_level + levels
                await db.execute(
                    "UPDATE levels SET level=? WHERE user_id=? AND guild_id=?",
                    (new_level, member.id, interaction.guild.id)
                )

            coin_reward = levels * 20

            await db.execute(
                "INSERT OR IGNORE INTO coins (user_id, balance) VALUES (?,0)",
                (member.id,)
            )
            await db.execute(
                "UPDATE coins SET balance = balance + ? WHERE user_id=?",
                (coin_reward, member.id)
            )

            await db.commit()

        card = await generate_rank_card(member, new_level, coin_reward)

        await interaction.channel.send(
            content=f"🆙 {member.mention} gained {levels} levels!",
            file=discord.File(card, "rank.png")
        )

        await interaction.followup.send("✅ Level updated.")

    # ---------------- ADMIN ADD XP ----------------
    @app_commands.command(name="addxp", description="Admin: Add XP to a user")
    @app_commands.checks.has_permissions(administrator=True)
    async def addxp(self, interaction: discord.Interaction, member: discord.Member, xp_amount: int):
        await interaction.response.defer(ephemeral=True)

        if xp_amount <= 0:
            return await interaction.followup.send("❌ XP must be positive.")

        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute(
                "SELECT xp, level FROM levels WHERE user_id=? AND guild_id=?",
                (member.id, interaction.guild.id)
            )
            row = await cur.fetchone()

            if not row:
                xp = xp_amount
                level = 1
            else:
                xp, level = row
                xp += xp_amount

            leveled_up = False
            coins = 0

            while xp >= xp_needed(level):
                xp -= xp_needed(level)
                level += 1
                leveled_up = True

                reward = 20
                if level % 5 == 0:
                    reward += 50
                coins += reward

            await db.execute(
                "INSERT OR REPLACE INTO levels (user_id, guild_id, xp, level) VALUES (?,?,?,?)",
                (member.id, interaction.guild.id, xp, level)
            )

            if coins > 0:
                await db.execute(
                    "INSERT OR IGNORE INTO coins (user_id, balance) VALUES (?,0)",
                    (member.id,)
                )
                await db.execute(
                    "UPDATE coins SET balance = balance + ? WHERE user_id=?",
                    (coins, member.id)
                )

            await db.commit()

        if leveled_up:
            card = await generate_rank_card(member, level, coins)
            await interaction.channel.send(
                content=f"🎉 {member.mention} leveled up!",
                file=discord.File(card, "rank.png")
            )

        await interaction.followup.send(
            f"✅ Added {xp_amount} XP\n📈 Level: {level}",
            ephemeral=True
        )


# ================= SETUP =================
async def setup(bot: commands.Bot):
    await bot.add_cog(Levels(bot))
