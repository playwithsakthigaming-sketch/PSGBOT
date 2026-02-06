import discord
import aiosqlite
import time
from discord.ext import commands, tasks
from discord import app_commands
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO

DB_NAME = "bot.db"

# ================= CONFIG =================
XP_PER_MESSAGE = 10
VOICE_XP_PER_MIN = 5
COINS_PER_LEVEL = 20

# Level-up messages go only here
LEVEL_UP_CHANNEL_ID = 123456789012345678  # change this

# Premium XP boost
PREMIUM_BOOST = {
    "bronze": 1.2,
    "silver": 1.5,
    "gold": 2.0
}

# Premium level-up effects
PREMIUM_ANIMATED = {
    "bronze": "assets/bronze_levelup.gif",
    "silver": "assets/silver_levelup.gif",
    "gold": "assets/gold_levelup.gif"
}

# Level roles
LEVEL_ROLES = {
    5: 111111111111111111,
    10: 222222222222222222,
    20: 333333333333333333
}


# ================= LEVEL FORMULA =================
def xp_needed(level: int):
    return 100 + (level * 50)


# ================= PREMIUM BOOST =================
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


async def get_premium_tier(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cur = await db.execute(
            "SELECT tier, expires FROM premium WHERE user_id=?",
            (user_id,)
        )
        row = await cur.fetchone()

    if not row:
        return None

    tier, expires = row
    if expires < int(time.time()):
        return None

    return tier


# ================= RANK CARD =================
def generate_rank_card(username, avatar_bytes, level, xp, needed, coins):
    W, H = 900, 300
    img = Image.new("RGB", (W, H), (20, 20, 20))
    draw = ImageDraw.Draw(img)

    try:
        name_font = ImageFont.truetype("fonts/CinzelDecorative-Bold.ttf", 50)
        level_font = ImageFont.truetype("fonts/CinzelDecorative-Bold.ttf", 36)
        small_font = ImageFont.truetype("fonts/CinzelDecorative-Bold.ttf", 26)
    except:
        name_font = level_font = small_font = ImageFont.load_default()

    avatar = Image.open(BytesIO(avatar_bytes)).resize((150, 150)).convert("RGBA")
    img.paste(avatar, (30, 75), avatar)

    draw.text((220, 40), username, font=name_font, fill="white")
    draw.text((220, 120), f"LEVEL {level}", font=level_font, fill="gold")
    draw.text((220, 160), f"+{coins} COINS", font=level_font, fill=(0, 255, 200))
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
            while xp >= xp_needed(level):
                xp -= xp_needed(level)
                level += 1
                coins += level * COINS_PER_LEVEL

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

        if coins > 0:
            await self.apply_level_roles(message.author, level)
            await self.send_levelup_effect(message.author, level, xp, coins)

    # ---------------- VOICE XP WITH AFK DETECTION ----------------
    @tasks.loop(minutes=1)
    async def voice_xp_loop(self):
        for guild in self.bot.guilds:
            for vc in guild.voice_channels:

                if len(vc.members) <= 1:
                    continue

                for member in vc.members:
                    if member.bot:
                        continue

                    state = member.voice
                    if not state:
                        continue

                    if state.self_mute or state.self_deaf or state.afk:
                        continue

                    user_id = member.id
                    guild_id = guild.id

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

                        boost = await get_xp_boost(user_id)
                        xp += int(VOICE_XP_PER_MIN * boost)

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

                    if coins > 0:
                        await self.apply_level_roles(member, level)
                        await self.send_levelup_effect(member, level, xp, coins)

    @voice_xp_loop.before_loop
    async def before_voice_loop(self):
        await self.bot.wait_until_ready()

    # ---------------- LEVEL-UP MESSAGE ----------------
    async def send_levelup_effect(self, member, level, xp, coins):
        channel = member.guild.get_channel(LEVEL_UP_CHANNEL_ID)
        if not channel:
            return

        avatar = await member.display_avatar.read()
        needed = xp_needed(level)

        card = generate_rank_card(
            member.name,
            avatar,
            level,
            xp,
            needed,
            coins
        )

        tier = await get_premium_tier(member.id)

        if tier and tier in PREMIUM_ANIMATED:
            try:
                await channel.send(
                    content=f"🎉 {member.mention} leveled up to **Level {level}**!",
                    files=[
                        discord.File(card, "rank.png"),
                        discord.File(PREMIUM_ANIMATED[tier], "effect.gif")
                    ]
                )
                return
            except:
                pass

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

            await db.commit()

        await interaction.response.send_message(
            f"✅ Added {amount} XP to {member.mention}"
        )


# ================= SETUP =================
async def setup(bot: commands.Bot):
    await bot.add_cog(Levels(bot))
