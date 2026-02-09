import discord
import aiosqlite
import aiohttp
import time
from discord.ext import commands, tasks
from discord import app_commands
import re
from datetime import datetime

DB_NAME = "bot.db"
REMINDER_BEFORE = 3600  # 1 hour before event

# -----------------------------------------------------
# JOIN BUTTON VIEW
# -----------------------------------------------------
class JoinEventView(discord.ui.View):
    def __init__(self, event_link: str):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                label="I Will Be There",
                style=discord.ButtonStyle.link,
                url=event_link,
                emoji="🚛"
            )
        )

# -----------------------------------------------------
# EVENT COG
# -----------------------------------------------------
class EventSystem(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.reminder_loop.start()
        self.update_loop.start()
        self.countdown_loop.start()

    def cog_unload(self):
        self.reminder_loop.cancel()
        self.update_loop.cancel()
        self.countdown_loop.cancel()

    # -----------------------------------------------------
    # DB INIT
    # -----------------------------------------------------
    async def init_db(self):
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT,
                    role_id INTEGER,
                    channel_id INTEGER,
                    slot_number INTEGER,
                    slot_image TEXT,
                    route_image TEXT,
                    start_time INTEGER,
                    reminded INTEGER DEFAULT 0,
                    message_id INTEGER,
                    created_by INTEGER
                )
            """)
            await db.commit()

    @commands.Cog.listener()
    async def on_ready(self):
        await self.init_db()

    # -----------------------------------------------------
    # REMINDER LOOP
    # -----------------------------------------------------
    @tasks.loop(minutes=1)
    async def reminder_loop(self):
        now = int(time.time())

        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute("""
                SELECT event_id, role_id, channel_id, start_time
                FROM events
                WHERE reminded = 0
            """)
            rows = await cur.fetchall()

            for event_id, role_id, channel_id, start_time in rows:
                if not start_time or not role_id or not channel_id:
                    continue

                if start_time - now <= REMINDER_BEFORE:
                    for guild in self.bot.guilds:
                        role = guild.get_role(role_id)
                        channel = guild.get_channel(channel_id)

                        if role and channel:
                            await channel.send(
                                f"🚛 {role.mention} **Convoy starting in 1 hour!**\n"
                                f"https://truckersmp.com/events/{event_id}"
                            )

                    await db.execute(
                        "UPDATE events SET reminded = 1 WHERE event_id=?",
                        (event_id,)
                    )
            await db.commit()

    # -----------------------------------------------------
    # AUTO UPDATE LOOP
    # -----------------------------------------------------
    @tasks.loop(minutes=10)
    async def update_loop(self):
        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute("""
                SELECT event_id, channel_id, message_id, role_id, slot_number
                FROM events
            """)
            rows = await cur.fetchall()

        for event_id, channel_id, message_id, role_id, slot_number in rows:
            data = await self.fetch_event(event_id)
            if not data:
                continue

            name = data.get("name", "Unknown")
            start_str = data.get("start_at")
            server = data.get("server", {}).get("name", "Unknown")

            departure = data.get("departure") or {}
            destination = data.get("arrival") or {}

            dep_text = f"{departure.get('city','Unknown')} ({departure.get('location','Unknown')})"

            dest_text = None
            if destination.get("city") or destination.get("location"):
                dest_text = f"{destination.get('city','Unknown')} ({destination.get('location','Unknown')})"

            banner = data.get("banner")
            event_link = f"https://truckersmp.com/events/{event_id}"

            for guild in self.bot.guilds:
                channel = guild.get_channel(channel_id)
                role = guild.get_role(role_id)

                if not channel or not role:
                    continue

                try:
                    msg = await channel.fetch_message(message_id)
                except:
                    continue

                embed = discord.Embed(
                    title=f"🚛 {name}",
                    url=event_link,
                    color=discord.Color.orange(),
                    description=role.mention
                )

                embed.add_field(name="📅 Date", value=start_str, inline=True)
                embed.add_field(name="🖥 Server", value=server, inline=True)
                embed.add_field(name="🅿 Slot", value=str(slot_number), inline=True)
                embed.add_field(name="📍 Departure", value=dep_text, inline=False)

                if dest_text:
                    embed.add_field(name="🏁 Destination", value=dest_text, inline=False)

                if banner:
                    embed.set_image(url=banner)

                await msg.edit(embed=embed)

    # -----------------------------------------------------
    # COUNTDOWN LOOP
    # -----------------------------------------------------
    @tasks.loop(minutes=1)
    async def countdown_loop(self):
        now = int(time.time())

        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute("""
                SELECT event_id, channel_id, message_id, role_id, slot_number, start_time
                FROM events
            """)
            rows = await cur.fetchall()

        for event_id, channel_id, message_id, role_id, slot_number, start_time in rows:
            if not start_time or start_time < now:
                continue

            remaining = start_time - now
            days = remaining // 86400
            hours = (remaining % 86400) // 3600
            minutes = (remaining % 3600) // 60
            countdown_text = f"{days}d {hours}h {minutes}m"

            data = await self.fetch_event(event_id)
            if not data:
                continue

            name = data.get("name", "Unknown")
            server = data.get("server", {}).get("name", "Unknown")
            start_str = data.get("start_at")

            departure = data.get("departure") or {}
            dep_text = f"{departure.get('city','Unknown')} ({departure.get('location','Unknown')})"

            banner = data.get("banner")
            event_link = f"https://truckersmp.com/events/{event_id}"

            for guild in self.bot.guilds:
                channel = guild.get_channel(channel_id)
                role = guild.get_role(role_id)

                if not channel or not role:
                    continue

                try:
                    msg = await channel.fetch_message(message_id)
                except:
                    continue

                embed = discord.Embed(
                    title=f"🚛 {name}",
                    url=event_link,
                    color=discord.Color.orange(),
                    description=f"{role.mention}\n⏳ **Starts in:** {countdown_text}"
                )

                embed.add_field(name="📅 Date", value=start_str, inline=True)
                embed.add_field(name="🖥 Server", value=server, inline=True)
                embed.add_field(name="🅿 Slot", value=str(slot_number), inline=True)
                embed.add_field(name="📍 Departure", value=dep_text, inline=False)

                if banner:
                    embed.set_image(url=banner)

                embed.set_footer(text="Live countdown")

                await msg.edit(embed=embed)

    # -----------------------------------------------------
    # HELPERS
    # -----------------------------------------------------
    def extract_event_id(self, text: str) -> str:
        match = re.search(r"(\d+)", text)
        return match.group(1) if match else text

    async def fetch_event(self, event_id: str):
        url = f"https://api.truckersmp.com/v2/events/{event_id}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                return data.get("response")

# ---------------------------------------------------------
# SETUP
# ---------------------------------------------------------
async def setup(bot: commands.Bot):
    await bot.add_cog(EventSystem(bot))
