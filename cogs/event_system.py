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

    def cog_unload(self):
        self.reminder_loop.cancel()

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
                    created_by INTEGER
                )
            """)
            await db.commit()

    @commands.Cog.listener()
    async def on_ready(self):
        await self.init_db()

    # -----------------------------------------------------
    # AUTO REMINDER LOOP
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

                        if not role or not channel:
                            continue

                        try:
                            await channel.send(
                                f"🚛 {role.mention} **Convoy starting in 1 hour!**\n"
                                f"https://truckersmp.com/events/{event_id}"
                            )
                        except:
                            pass

                    await db.execute(
                        "UPDATE events SET reminded = 1 WHERE event_id=?",
                        (event_id,)
                    )

            await db.commit()

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

    # -----------------------------------------------------
    # /event COMMAND
    # -----------------------------------------------------
    @app_commands.command(
        name="event",
        description="📅 Create TruckersMP event with reminder"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def create_event(
        self,
        interaction: discord.Interaction,
        eventurl: str,
        role: discord.Role,
        channel: discord.TextChannel,
        slotnumber: int,
        slotimage: str,
        routeimage: str
    ):
        await interaction.response.defer()

        event_id = self.extract_event_id(eventurl)
        data = await self.fetch_event(event_id)

        if not data:
            return await interaction.followup.send(
                "❌ Could not fetch event details.",
                ephemeral=True
            )

        # Extract details
        name = data.get("name", "Unknown")
        start_str = data.get("start_at")
        server = data.get("server", {}).get("name", "Unknown")

        dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
        start_timestamp = int(dt.timestamp())

        departure = data.get("departure") or {}
        destination = data.get("arrival") or {}

        dep_text = f"{departure.get('city', 'Unknown')} ({departure.get('location', 'Unknown')})"
        dest_text = f"{destination.get('city', 'Unknown')} ({destination.get('location', 'Unknown')})"

        banner = data.get("banner")
        event_link = f"https://truckersmp.com/events/{event_id}"

        # Save to DB
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("""
                INSERT INTO events (
                    event_id, role_id, channel_id,
                    slot_number, slot_image, route_image,
                    start_time, reminded, created_by
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
            """, (
                event_id,
                role.id,
                channel.id,
                slotnumber,
                slotimage,
                routeimage,
                start_timestamp,
                interaction.user.id
            ))
            await db.commit()

        # ---------------- MAIN EVENT EMBED ----------------
        main_embed = discord.Embed(
            title=f"🚛 {name}",
            url=event_link,
            color=discord.Color.orange(),
            description=role.mention
        )

        main_embed.add_field(name="📅 Date", value=start_str, inline=True)
        main_embed.add_field(name="🖥 Server", value=server, inline=True)
        main_embed.add_field(name="🅿 Slot", value=str(slotnumber), inline=True)
        main_embed.add_field(name="📍 Departure", value=dep_text, inline=False)
        main_embed.add_field(name="🏁 Destination", value=dest_text, inline=False)

        if banner:
            main_embed.set_image(url=banner)

        main_embed.set_footer(text=f"Created by {interaction.user}")

        # ---------------- ROUTE EMBED ----------------
        route_embed = discord.Embed(
            title="🗺️ Event Route",
            color=discord.Color.blue()
        )
        route_embed.set_image(url=routeimage)

        # ---------------- SLOT EMBED ----------------
        slot_embed = discord.Embed(
            title="🅿 Slot Information",
            color=discord.Color.green()
        )
        slot_embed.set_image(url=slotimage)

        view = JoinEventView(event_link)

        await interaction.followup.send(
            embeds=[main_embed, route_embed, slot_embed],
            view=view
        )

    # -----------------------------------------------------
    # /event_calendar COMMAND
    # -----------------------------------------------------
    @app_commands.command(
        name="event_calendar",
        description="📅 View upcoming convoy events"
    )
    async def event_calendar(self, interaction: discord.Interaction):
        now = int(time.time())

        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute("""
                SELECT event_id, slot_number, start_time
                FROM events
                WHERE start_time > ?
                ORDER BY start_time ASC
                LIMIT 10
            """, (now,))
            rows = await cur.fetchall()

        if not rows:
            return await interaction.response.send_message(
                "❌ No upcoming events.",
                ephemeral=True
            )

        embed = discord.Embed(
            title="📅 Upcoming Convoy Calendar",
            color=discord.Color.orange()
        )

        for event_id, slot, start_time in rows:
            date = f"<t:{start_time}:F>"
            link = f"https://truckersmp.com/events/{event_id}"

            embed.add_field(
                name=f"🚛 Event {event_id}",
                value=(
                    f"📅 {date}\n"
                    f"🅿 Slot: {slot}\n"
                    f"[View Event]({link})"
                ),
                inline=False
            )

        await interaction.response.send_message(embed=embed)

# ---------------------------------------------------------
# SETUP
# ---------------------------------------------------------
async def setup(bot: commands.Bot):
    await bot.add_cog(EventSystem(bot))
