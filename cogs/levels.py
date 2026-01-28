import discord
import aiosqlite
import time
import math
import requests
from io import BytesIO
from PIL import Image, ImageDraw
from discord.ext import commands, tasks
from discord import app_commands

# =========================================================
# CONFIG
# =========================================================

CHAT_XP = 10
CHAT_XP_COOLDOWN = 30        # seconds

VC_XP = 15                  # XP per interval
VC_INTERVAL_MINUTES = 5
VC_MIN_ACTIVE_MINUTES = 20  # AFK detection

LEVEL_XP_BASE = 100         # base XP
LEVEL_XP_MULTIPLIER = 1.5   # curve

# =========================================================
# XP / LEVEL HELPERS
# =========================================================

def xp_for_next_level(level: int) -> int:
    return int(LEVEL_XP_BASE * (level ** LEVEL_XP_MULTIPLIER))

# =========================================================
# ANIMATED RANK CARD (GIF)
# =========================================================

def generate_animated_rank_card(
    user: discord.User,
    level: int,
    xp: int,
    max_xp: int,
    tier: str | None,
    style: str
):
    frames = []
    width, height = 800, 260

    avatar = Image.open(
        BytesIO(requests.get(user.display_avatar.url).content)
    ).resize((140, 140)).convert("RGBA")

    for i in range(14):
        # ---------- BACKGROUND ----------
        if style == "dark":
            bg = (15, 15, 15)
        elif style == "neon":
            bg = (10, 10, 25)
        else:
            bg = (25, 25, 25)

        img = Image.new("RGB", (width, height), bg)
        draw = ImageDraw.Draw(img)

        # ---------- GLOW ----------
        glow = int(120 + 80 * math.sin(i / 14 * math.pi * 2))
        if tier == "gold":
            glow_color = (255, glow, 80)
        elif tier == "silver":
            glow_color = (180, 180, glow)
        elif tier == "bronze":
            glow_color = (glow, 120, 80)
        else:
            glow_color = (glow, glow, glow)

        draw.rounded_rectangle(
            (10, 10, width - 10, height - 10),
            radius=28,
            outline=glow_color,
            width=6
        )

        # ---------- AVATAR ----------
        bounce = int(8 * math.sin(i / 14 * math.pi * 2))
        img.paste(avatar, (40, 60 + bounce), avatar)

        # ---------- TEXT ----------
        draw.text((210, 65), user.name, fill="white")
        draw.text((210, 105), f"Level {level}", fill=glow_color)

        # ---------- XP BAR ----------
        bar_x, bar_y = 210, 160
        bar_w, bar_h = 500, 22
        progress = int(bar_w * min(xp / max_xp, 1))

        draw.rounded_rectangle(
            (bar_x, bar_y, bar_x + bar_w, bar_y + bar_h),
            radius=12,
            fill=(50, 50, 50)
        )
        draw.rounded_rectangle(
            (bar_x, bar_y, bar_x + progress, bar_y + bar_h),
            radius=12,
            fill=glow_color
        )

        # ---------- PREMIUM WATERMARK ----------
        if tier:
            draw.text(
                (width - 220, height - 40),
                "★ PREMIUM ★",
                fill=(255, 215, 0)
            )

        frames.append(img)

    buf = BytesIO()
    frames[0].save(
        buf,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=80,
        loop=0
    )
    buf.seek(0)
    return buf

# =========================================================
# LEVELS COG
# =========================================================

class Levels(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.chat_cooldown = {}
        self.vc_join_time = {}
        self.vc_xp_loop.start()

    # -----------------------------------------------------
    # CHAT XP
    # -----------------------------------------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        now = time.time()
        last = self.chat_cooldown.get(message.author.id, 0)
        if now - last < CHAT_XP_COOLDOWN:
            return

        self.chat_cooldown[message.author.id] = now
        await self.add_xp(message.author.id, message.guild.id, CHAT_XP)

    # -----------------------------------------------------
    # VC JOIN / LEAVE
    # -----------------------------------------------------
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return

        if after.channel and not before.channel:
            self.vc_join_time[member.id] = time.time()

        if before.channel and not after.channel:
            self.vc_join_time.pop(member.id, None)

    # -----------------------------------------------------
    # VC XP LOOP
    # -----------------------------------------------------
    @tasks.loop(minutes=VC_INTERVAL_MINUTES)
    async def vc_xp_loop(self):
        now = time.time()

        for guild in self.bot.guilds:
            for vc in guild.voice_channels:
                for member in vc.members:
                    if member.bot:
                        continue
                    if member.voice.self_mute or member.voice.afk:
                        continue

                    joined = self.vc_join_time.get(member.id)
                    if not joined or now - joined < VC_MIN_ACTIVE_MINUTES * 60:
                        continue

                    await self.add_xp(member.id, guild.id, VC_XP)

    # -----------------------------------------------------
    # XP ADDER + LEVEL UP
    # -----------------------------------------------------
    async def add_xp(self, user_id: int, guild_id: int, amount: int):
        async with aiosqlite.connect("bot.db") as db:
            await db.execute(
                "INSERT OR IGNORE INTO levels (user_id, guild_id, xp, level) VALUES (?,?,0,1)",
                (user_id, guild_id)
            )

            cur = await db.execute(
                "SELECT xp, level FROM levels WHERE user_id=? AND guild_id=?",
                (user_id, guild_id)
            )
            xp, level = await cur.fetchone()

            xp += amount
            needed = xp_for_next_level(level)

            if xp >= needed:
                xp -= needed
                level += 1

            await db.execute(
                "UPDATE levels SET xp=?, level=? WHERE user_id=? AND guild_id=?",
                (xp, level, user_id, guild_id)
            )
            await db.commit()

    # -----------------------------------------------------
    # /LEVEL COMMAND
    # -----------------------------------------------------
    @app_commands.command(name="level", description="📊 View your level")
    async def level(self, interaction: discord.Interaction):
        async with aiosqlite.connect("bot.db") as db:
            cur = await db.execute(
                "SELECT xp, level FROM levels WHERE user_id=? AND guild_id=?",
                (interaction.user.id, interaction.guild.id)
            )
            row = await cur.fetchone()

        if not row:
            return await interaction.response.send_message(
                "❌ You have no XP yet.",
                ephemeral=True
            )

        xp, level = row
        needed = xp_for_next_level(level)

        await interaction.response.send_message(
            f"⭐ **Level {level}**\n"
            f"📊 XP: `{xp}/{needed}`",
            ephemeral=True
        )

    # -----------------------------------------------------
    # /RANK COMMAND (ANIMATED)
    # -----------------------------------------------------
    @app_commands.command(name="rank", description="🎞️ View animated rank card")
    @app_commands.describe(style="glow / dark / neon")
    async def rank(self, interaction: discord.Interaction, style: str = "glow"):
        async with aiosqlite.connect("bot.db") as db:
            cur = await db.execute(
                "SELECT xp, level FROM levels WHERE user_id=? AND guild_id=?",
                (interaction.user.id, interaction.guild.id)
            )
            row = await cur.fetchone()

            if not row:
                return await interaction.response.send_message(
                    "❌ No rank data yet.",
                    ephemeral=True
                )

            xp, level = row

            cur = await db.execute(
                "SELECT tier FROM premium WHERE user_id=?",
                (interaction.user.id,)
            )
            prem = await cur.fetchone()
            tier = prem[0] if prem else None

        max_xp = xp_for_next_level(level)
        gif = generate_animated_rank_card(
            interaction.user,
            level,
            xp,
            max_xp,
            tier,
            style.lower()
        )

        await interaction.response.send_message(
            file=discord.File(gif, "rank.gif")
        )

# =========================================================
# SETUP
# =========================================================

async def setup(bot: commands.Bot):
    await bot.add_cog(Levels(bot))
