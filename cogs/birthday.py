import discord
import aiosqlite
import datetime
from discord.ext import commands, tasks
from discord import app_commands
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO

DB_NAME = "bot.db"


# ================= DATABASE =================
async def setup_database():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS birthdays (
            user_id INTEGER,
            guild_id INTEGER,
            day INTEGER,
            month INTEGER,
            year INTEGER,
            message TEXT,
            PRIMARY KEY (user_id, guild_id)
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS birthday_settings (
            guild_id INTEGER PRIMARY KEY,
            channel_id INTEGER
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS birthday_rewards (
            user_id INTEGER,
            guild_id INTEGER,
            streak INTEGER DEFAULT 0,
            last_year INTEGER,
            background TEXT DEFAULT "default",
            PRIMARY KEY (user_id, guild_id)
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS coins (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER DEFAULT 0
        )
        """)

        await db.commit()


# ================= IMAGE GENERATORS =================
def generate_card(username, age):
    img = Image.new("RGB", (800, 300), (255, 182, 193))
    draw = ImageDraw.Draw(img)

    try:
        font_big = ImageFont.truetype("arial.ttf", 60)
        font_small = ImageFont.truetype("arial.ttf", 40)
    except:
        font_big = ImageFont.load_default()
        font_small = ImageFont.load_default()

    draw.text((50, 80), "Happy Birthday!", font=font_big, fill=(255, 255, 255))
    draw.text((50, 170), f"{username} - {age} years old", font=font_small, fill=(255, 255, 255))

    buffer = BytesIO()
    img.save(buffer, "PNG")
    buffer.seek(0)
    return buffer


def generate_animated_profile(username, age, streak, background="default"):
    frames = []

    colors = {
        "default": (30, 30, 30),
        "neon": (10, 10, 40),
        "gold": (60, 45, 10),
        "space": (5, 5, 20),
        "anime": (60, 20, 60)
    }

    bg_color = colors.get(background, (30, 30, 30))

    try:
        font_big = ImageFont.truetype("arial.ttf", 40)
        font_small = ImageFont.truetype("arial.ttf", 25)
    except:
        font_big = ImageFont.load_default()
        font_small = ImageFont.load_default()

    for i in range(6):
        img = Image.new("RGB", (500, 250), bg_color)
        draw = ImageDraw.Draw(img)

        glow = 100 + i * 20
        draw.text((30, 30), username, font=font_big, fill=(255, glow, 0))
        draw.text((30, 120), f"Age: {age}", font=font_small, fill=(255, 255, 255))
        draw.text((30, 170), f"Streak: {streak} years", font=font_small, fill=(0, 255, 0))

        frames.append(img)

    buffer = BytesIO()
    frames[0].save(
        buffer,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=120,
        loop=0
    )
    buffer.seek(0)
    return buffer


# ================= COG =================
class Birthday(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.loop.create_task(setup_database())
        self.check_birthdays.start()

    def cog_unload(self):
        self.check_birthdays.cancel()

    # ---------- SET CHANNEL ----------
    @app_commands.command(name="set_birthday_channel")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_birthday_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.defer(ephemeral=True)

        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "INSERT OR REPLACE INTO birthday_settings(guild_id, channel_id) VALUES(?,?)",
                (interaction.guild.id, channel.id)
            )
            await db.commit()

        await interaction.followup.send("🎂 Birthday channel set.", ephemeral=True)

    # ---------- SET BIRTHDAY ----------
    @app_commands.command(name="set_birthday")
    async def set_birthday(self, interaction: discord.Interaction, day: int, month: int, year: int, message: str = "Have an awesome day!"):
        await interaction.response.defer(ephemeral=True)

        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("""
            INSERT OR REPLACE INTO birthdays(user_id, guild_id, day, month, year, message)
            VALUES (?,?,?,?,?,?)
            """, (interaction.user.id, interaction.guild.id, day, month, year, message))
            await db.commit()

        await interaction.followup.send("🎂 Birthday saved!", ephemeral=True)

    # ---------- SET BACKGROUND ----------
    @app_commands.command(name="birthday_background")
    async def birthday_background(self, interaction: discord.Interaction, background: str):
        await interaction.response.defer(ephemeral=True)

        valid = ["default", "neon", "gold", "space", "anime"]
        if background not in valid:
            return await interaction.followup.send(
                f"Invalid background. Choose: {', '.join(valid)}",
                ephemeral=True
            )

        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("""
            INSERT OR IGNORE INTO birthday_rewards(user_id, guild_id)
            VALUES (?,?)
            """, (interaction.user.id, interaction.guild.id))

            await db.execute("""
            UPDATE birthday_rewards
            SET background=?
            WHERE user_id=? AND guild_id=?
            """, (background, interaction.user.id, interaction.guild.id))

            await db.commit()

        await interaction.followup.send("Background updated.", ephemeral=True)

    # ---------- PROFILE ----------
    @app_commands.command(name="birthday_profile")
    async def birthday_profile(self, interaction: discord.Interaction, member: discord.Member = None):
        await interaction.response.defer()

        member = member or interaction.user
        current_year = datetime.datetime.utcnow().year

        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute("""
            SELECT b.year, r.streak, r.background
            FROM birthdays b
            LEFT JOIN birthday_rewards r
            ON b.user_id=r.user_id AND b.guild_id=r.guild_id
            WHERE b.user_id=? AND b.guild_id=?
            """, (member.id, interaction.guild.id))
            row = await cur.fetchone()

        if not row:
            return await interaction.followup.send("Birthday not set.")

        birth_year, streak, background = row
        streak = streak or 0
        background = background or "default"
        age = current_year - birth_year

        gif = generate_animated_profile(member.name, age, streak, background)
        file = discord.File(gif, filename="profile.gif")

        embed = discord.Embed(title=f"{member.name}'s Birthday Profile")
        embed.set_image(url="attachment://profile.gif")

        await interaction.followup.send(embed=embed, file=file)

    # ---------- LEADERBOARD ----------
    @app_commands.command(name="birthday_leaderboard", description="Oldest members leaderboard")
    async def birthday_leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer()

        current_year = datetime.datetime.utcnow().year

        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute("""
            SELECT user_id, year FROM birthdays
            WHERE guild_id=?
            ORDER BY year ASC
            LIMIT 10
            """, (interaction.guild.id,))
            rows = await cur.fetchall()

        if not rows:
            return await interaction.followup.send("No birthdays set.")

        desc = ""
        for i, (user_id, birth_year) in enumerate(rows, start=1):
            member = interaction.guild.get_member(user_id)
            if not member:
                continue
            age = current_year - birth_year
            desc += f"{i}. {member.mention} — {age} years old\n"

        embed = discord.Embed(title="🏆 Birthday Leaderboard", description=desc)
        await interaction.followup.send(embed=embed)

    # ---------- DAILY CHECK WITH AUTO DM ----------
    @tasks.loop(hours=24)
    async def check_birthdays(self):
        await self.bot.wait_until_ready()

        today = datetime.datetime.utcnow()
        day = today.day
        month = today.month
        year = today.year

        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute("""
            SELECT user_id, guild_id, year, message
            FROM birthdays
            WHERE day=? AND month=?
            """, (day, month))
            rows = await cur.fetchall()

            for user_id, guild_id, birth_year, message in rows:
                guild = self.bot.get_guild(guild_id)
                if not guild:
                    continue

                member = guild.get_member(user_id)
                if not member:
                    continue

                age = year - birth_year

                # STREAK
                cur2 = await db.execute("""
                SELECT streak, last_year, background
                FROM birthday_rewards
                WHERE user_id=? AND guild_id=?
                """, (user_id, guild_id))
                reward_row = await cur2.fetchone()

                streak = 1
                background = "default"

                if reward_row:
                    old_streak, last_year, bg = reward_row
                    background = bg or "default"
                    if last_year == year - 1:
                        streak = old_streak + 1

                reward = streak * 100

                # update coins
                await db.execute("""
                INSERT INTO coins(user_id, balance)
                VALUES (?,?)
                ON CONFLICT(user_id) DO UPDATE
                SET balance = balance + ?
                """, (user_id, reward, reward))

                # save streak
                await db.execute("""
                INSERT OR REPLACE INTO birthday_rewards
                (user_id, guild_id, streak, last_year, background)
                VALUES (?,?,?,?,?)
                """, (user_id, guild_id, streak, year, background))

                # channel message
                cur3 = await db.execute(
                    "SELECT channel_id FROM birthday_settings WHERE guild_id=?",
                    (guild_id,)
                )
                row = await cur3.fetchone()
                if row:
                    channel = guild.get_channel(row[0])
                    if channel:
                        card = generate_card(member.name, age)
                        file = discord.File(card, filename="birthday.png")

                        embed = discord.Embed(
                            title="🎉 Happy Birthday!",
                            description=f"{member.mention}\n{message}\n🎁 Reward: {reward} coins",
                            color=discord.Color.gold()
                        )
                        embed.set_image(url="attachment://birthday.png")

                        await channel.send(embed=embed, file=file)

                # DM animated profile
                try:
                    gif = generate_animated_profile(member.name, age, streak, background)
                    gif_file = discord.File(gif, filename="profile.gif")

                    dm_embed = discord.Embed(
                        title="🎂 Your Birthday Profile",
                        description=f"Happy Birthday {member.name}!\n"
                                    f"🎁 Reward: {reward} coins\n"
                                    f"🔥 Streak: {streak} years",
                        color=discord.Color.blurple()
                    )
                    dm_embed.set_image(url="attachment://profile.gif")

                    await member.send(embed=dm_embed, file=gif_file)
                except:
                    pass

            await db.commit()

    @check_birthdays.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()


# ================= SETUP =================
async def setup(bot: commands.Bot):
    await bot.add_cog(Birthday(bot))
