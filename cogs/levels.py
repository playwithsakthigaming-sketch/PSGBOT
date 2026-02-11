import discord
import aiosqlite
import time
from discord.ext import commands, tasks
from discord import app_commands
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO

DB_NAME = "bot.db"

# ================= CONFIG =================
XP_PER_MESSAGE = 8
VOICE_XP_PER_MIN = 9
COINS_PER_LEVEL = 10

LEVEL_UP_CHANNEL_ID = 1415142396341256275

PREMIUM_BOOST = {
    "bronze": 1.2,
    "silver": 1.5,
    "gold": 2.0
}

LEVEL_ROLES = {
    5: 1464425870675411064,
    10: 222222222222222222,
    20: 333333333333333333
}


# ================= LEVEL FORMULA =================
def xp_needed(level: int):
    return 100 + (level * 50)


# ================= PREMIUM HELPERS =================
async def get_xp_boost(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cur = await db.execute(
            "SELECT tier, expires FROM premium WHERE user_id=?",
            (user_id,)
        )
        row = await cur.fetchone()

    if not row:
        return 1.0

    tier, expires = row
    if expires < int(time.time()):
        return 1.0

    return PREMIUM_BOOST.get(tier, 1.0)


# ================= RANK CARD =================
def generate_rank_card(username, avatar_bytes, level, xp, needed, coins):
    W, H = 900, 300
    img = Image.new("RGB", (W, H), (20, 20, 20))
    draw = ImageDraw.Draw(img)

    try:
        name_font = ImageFont.truetype("fonts/CinzelDecorative-Bold.ttf", 50)
        level_font = ImageFont.truetype("fonts/CinzelDecorative-Bold.ttf", 33)
        small_font = ImageFont.truetype("fonts/CinzelDecorative-Bold.ttf", 26)
    except:
        name_font = level_font = small_font = ImageFont.load_default()

    avatar = Image.open(BytesIO(avatar_bytes)).resize((150, 150)).convert("RGBA")
    img.paste(avatar, (30, 75), avatar)

    draw.text((220, 40), username, font=name_font, fill="white")
    draw.text((220, 120), f"LEVEL {level}", font=level_font, fill="gold")
    draw.text((220, 160), f"{coins} COINS", font=level_font, fill=(0, 255, 200))
    draw.text((220, 210), f"XP: {xp} / {needed}", font=small_font, fill="white")

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
        self.voice_xp_loop.start()

    async def cog_load(self):
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS levels (
                    user_id INTEGER,
                    guild_id INTEGER,
                    xp INTEGER,
                    level INTEGER,
                    PRIMARY KEY (user_id, guild_id)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS coins (
                    user_id INTEGER PRIMARY KEY,
                    balance INTEGER DEFAULT 0
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS premium (
                    user_id INTEGER PRIMARY KEY,
                    tier TEXT,
                    expires INTEGER
                )
            """)
            await db.commit()

    # ---------------- APPLY LEVEL ROLES ----------------
    async def apply_level_roles(self, member: discord.Member, level: int):
        for lvl, role_id in LEVEL_ROLES.items():
            role = member.guild.get_role(role_id)
            if not role:
                continue
            try:
                if level >= lvl:
                    await member.add_roles(role)
                else:
                    await member.remove_roles(role)
            except:
                pass

    # ---------------- CHAT XP ----------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not message.guild:
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

            boost = await get_xp_boost(user_id)
            xp += int(XP_PER_MESSAGE * boost)

            coins = 0
            leveled_up = False

            while xp >= xp_needed(level):
                xp -= xp_needed(level)
                level += 1
                coins += level * COINS_PER_LEVEL
                leveled_up = True

            await db.execute(
                "UPDATE levels SET xp=?, level=? WHERE user_id=? AND guild_id=?",
                (xp, level, user_id, guild_id)
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

        if leveled_up:
            await self.apply_level_roles(message.author, level)
            await self.send_levelup_effect(message.author, level, xp, coins)

    # ---------------- VOICE XP LOOP ----------------
    @tasks.loop(minutes=1)
    async def voice_xp_loop(self):
        for guild in self.bot.guilds:
            for vc in guild.voice_channels:
                for member in vc.members:
                    if member.bot:
                        continue

                    boost = await get_xp_boost(member.id)
                    xp_gain = int(VOICE_XP_PER_MIN * boost)

                    async with aiosqlite.connect(DB_NAME) as db:
                        cur = await db.execute(
                            "SELECT xp, level FROM levels WHERE user_id=? AND guild_id=?",
                            (member.id, guild.id)
                        )
                        row = await cur.fetchone()

                        if not row:
                            xp = 0
                            level = 1
                        else:
                            xp, level = row

                        xp += xp_gain
                        coins = 0
                        leveled_up = False

                        while xp >= xp_needed(level):
                            xp -= xp_needed(level)
                            level += 1
                            coins += level * COINS_PER_LEVEL
                            leveled_up = True

                        await db.execute(
                            "INSERT OR REPLACE INTO levels (user_id, guild_id, xp, level) VALUES (?,?,?,?)",
                            (member.id, guild.id, xp, level)
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
                        await self.apply_level_roles(member, level)
                        await self.send_levelup_effect(member, level, xp, coins)

    # ---------------- LEVEL-UP MESSAGE ----------------
    async def send_levelup_effect(self, member, level, xp, coins):
        channel = member.guild.get_channel(LEVEL_UP_CHANNEL_ID)
        if not channel:
            return

        avatar = await member.display_avatar.read()
        needed = xp_needed(level)

        card = generate_rank_card(member.name, avatar, level, xp, needed, coins)

        await channel.send(
            content=f"🎉 {member.mention} leveled up to **Level {level}**!",
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
                return await interaction.response.send_message(
                    "No level data yet.", ephemeral=True
                )

            xp, level = row

            await db.execute(
                "INSERT OR IGNORE INTO coins (user_id, balance) VALUES (?,0)",
                (user_id,)
            )

            cur = await db.execute(
                "SELECT balance FROM coins WHERE user_id=?",
                (user_id,)
            )
            coin_row = await cur.fetchone()
            coins = coin_row[0] if coin_row else 0

        needed = xp_needed(level)
        avatar = await member.display_avatar.read()
        card = generate_rank_card(member.name, avatar, level, xp, needed, coins)

        await interaction.response.send_message(
            file=discord.File(card, "rank.png"),
            ephemeral=True
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
            leveled_up = False

            while xp >= xp_needed(level):
                xp -= xp_needed(level)
                level += 1
                coins += level * COINS_PER_LEVEL
                leveled_up = True

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

        if leveled_up:
            await self.apply_level_roles(member, level)
            await self.send_levelup_effect(member, level, xp, coins)

        await interaction.response.send_message(
            f"✅ Added **{amount} XP** to {member.mention}",
            ephemeral=True
        )


# ================= SETUP =================
async def setup(bot: commands.Bot):
    await bot.add_cog(Levels(bot))
