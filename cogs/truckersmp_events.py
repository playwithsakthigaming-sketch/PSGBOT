import discord
import aiosqlite
import aiohttp
import re
from datetime import datetime, timedelta, timezone
from discord.ext import commands, tasks
from discord import app_commands
from bs4 import BeautifulSoup

DB_NAME = "events.db"
API_EVENT = "https://api.truckersmp.com/v2/events/{}"

IST = timezone(timedelta(hours=5, minutes=30))


# =========================================================
# HELPERS
# =========================================================

def extract_event_id(value: str) -> int | None:
    if value.isdigit():
        return int(value)

    match = re.search(r"/events/(\d+)", value)
    if match:
        return int(match.group(1))

    return None


async def fetch_event(event_id: int):
    async with aiohttp.ClientSession() as session:
        async with session.get(API_EVENT.format(event_id)) as res:
            if res.status != 200:
                return None
            data = await res.json()
            return data.get("response")


async def fetch_route_image(event_url: str) -> str | None:
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        async with aiohttp.ClientSession() as session:
            async with session.get(event_url, headers=headers) as res:
                if res.status != 200:
                    return None

                html = await res.text()
                soup = BeautifulSoup(html, "html.parser")

                for header in soup.find_all(["h2", "h3", "h4"]):
                    if "route" in header.text.lower():
                        section = header.find_next("div")
                        if section:
                            img = section.find("img")
                            if img and img.get("src"):
                                src = img["src"]
                                if src.startswith("/"):
                                    return "https://truckersmp.com" + src
                                return src
    except:
        pass

    return None


# =========================================================
# COG
# =========================================================

class TruckersMPEvents(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.calendar_message_id = None
        self.calendar_channel_id = None
        self.reminder_loop.start()
        self.cleanup_loop.start()
        self.calendar_loop.start()

    def cog_unload(self):
        self.reminder_loop.cancel()
        self.cleanup_loop.cancel()
        self.calendar_loop.cancel()

    async def init_db(self):
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    event_id INTEGER,
                    guild_id INTEGER,
                    role_id INTEGER,
                    event_date TEXT,
                    slot_number INTEGER,
                    slot_image TEXT
                )
            """)
            await db.commit()

    # -----------------------------------------------------
    # /event
    # -----------------------------------------------------
    @app_commands.command(name="event", description="Post a TruckersMP event")
    async def event(
        self,
        interaction: discord.Interaction,
        event: str,
        channel: discord.TextChannel,
        role: discord.Role,
        slot_number: int,
        slot_image: str | None = None
    ):
        await interaction.response.defer()

        event_id = extract_event_id(event)
        if not event_id:
            return await interaction.followup.send("❌ Invalid event link or ID.")

        data = await fetch_event(event_id)
        if not data:
            return await interaction.followup.send("❌ Event not found.")

        title = data["name"]
        description = data["description"][:1000]
        start_time = data["start_at"]
        server = data["server"]["name"]
        banner = data.get("banner")
        url = f"https://truckersmp.com/events/{event_id}"

        dt_utc = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        dt_ist = dt_utc.astimezone(IST)
        event_date = dt_ist.strftime("%Y-%m-%d")

        route_image = await fetch_route_image(url)

        # MAIN EMBED
        embed = discord.Embed(
            title=title,
            url=url,
            description=description,
            color=discord.Color.blue()
        )
        embed.add_field(name="Server", value=server, inline=True)
        embed.add_field(name="Date (IST)", value=dt_ist.strftime("%d %b %Y"), inline=True)
        embed.add_field(name="Time (IST)", value=dt_ist.strftime("%H:%M"), inline=True)

        if banner:
            embed.set_image(url=banner)

        # ROUTE EMBED
        route_embed = None
        if route_image:
            route_embed = discord.Embed(
                title="🗺 Event Route",
                color=discord.Color.green()
            )
            route_embed.set_image(url=route_image)

        # SLOT EMBED
        slot_embed = discord.Embed(
            title="🚚 Slot Information",
            color=discord.Color.green()
        )
        slot_embed.add_field(name="Slot Number", value=str(slot_number))

        if slot_image:
            slot_embed.set_image(url=slot_image)

        await channel.send(role.mention)
        await channel.send(embed=embed)

        if route_embed:
            await channel.send(embed=route_embed)

        await channel.send(embed=slot_embed)

        # Save event
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?)",
                (event_id, interaction.guild.id, role.id, event_date, slot_number, slot_image)
            )
            await db.commit()

        await interaction.followup.send("✅ Event posted and reminder scheduled.")

    # -----------------------------------------------------
    # /calendar
    # -----------------------------------------------------
    @app_commands.command(name="calendar", description="Create event calendar")
    async def calendar(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.defer()

        embed = await self.build_calendar_embed()
        msg = await channel.send(embed=embed)

        self.calendar_channel_id = channel.id
        self.calendar_message_id = msg.id

        await interaction.followup.send("📅 Calendar created and auto-refresh enabled.")

    async def build_calendar_embed(self):
        embed = discord.Embed(
            title="📅 Event Calendar",
            color=discord.Color.orange()
        )

        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute(
                "SELECT event_id, event_date FROM events ORDER BY event_date"
            ) as cursor:
                rows = await cursor.fetchall()

        if not rows:
            embed.description = "No upcoming events."
            return embed

        lines = []
        for event_id, event_date in rows:
            dt = datetime.strptime(event_date, "%Y-%m-%d")
            formatted = dt.strftime("%d %b %Y")
            url = f"https://truckersmp.com/events/{event_id}"
            lines.append(f"**{formatted}** → [Event Link]({url})")

        embed.description = "\n".join(lines)
        return embed

    # -----------------------------------------------------
    # CALENDAR AUTO REFRESH
    # -----------------------------------------------------
    @tasks.loop(minutes=2)
    async def calendar_loop(self):
        if not self.calendar_channel_id or not self.calendar_message_id:
            return

        channel = self.bot.get_channel(self.calendar_channel_id)
        if not channel:
            return

        try:
            msg = await channel.fetch_message(self.calendar_message_id)
            embed = await self.build_calendar_embed()
            await msg.edit(embed=embed)
        except:
            pass

    # -----------------------------------------------------
    # REMINDER LOOP (7 AM IST)
    # -----------------------------------------------------
    @tasks.loop(minutes=30)
    async def reminder_loop(self):
        now_ist = datetime.now(IST)

        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT * FROM events") as cursor:
                rows = await cursor.fetchall()

        for event_id, guild_id, role_id, event_date, slot_number, slot_image in rows:
            try:
                event_day = datetime.strptime(event_date, "%Y-%m-%d").date()

                if now_ist.date() == event_day and now_ist.hour == 7:
                    guild = self.bot.get_guild(guild_id)
                    if not guild:
                        continue

                    role = guild.get_role(role_id)
                    if not role:
                        continue

                    data = await fetch_event(event_id)
                    if not data:
                        continue

                    title = data["name"]
                    description = data["description"][:1000]
                    start_time = data["start_at"]
                    server = data["server"]["name"]
                    banner = data.get("banner")
                    url = f"https://truckersmp.com/events/{event_id}"

                    dt_utc = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                    dt_ist = dt_utc.astimezone(IST)

                    route_image = await fetch_route_image(url)

                    main_embed = discord.Embed(
                        title=title,
                        url=url,
                        description=description,
                        color=discord.Color.blue()
                    )
                    main_embed.add_field(name="Server", value=server, inline=True)
                    main_embed.add_field(name="Date (IST)", value=dt_ist.strftime("%d %b %Y"), inline=True)
                    main_embed.add_field(name="Time (IST)", value=dt_ist.strftime("%H:%M"), inline=True)

                    if banner:
                        main_embed.set_image(url=banner)

                    route_embed = None
                    if route_image:
                        route_embed = discord.Embed(
                            title="🗺 Event Route",
                            color=discord.Color.green()
                        )
                        route_embed.set_image(url=route_image)

                    slot_embed = discord.Embed(
                        title="🚚 Slot Information",
                        color=discord.Color.green()
                    )
                    slot_embed.add_field(name="Slot Number", value=str(slot_number))

                    if slot_image:
                        slot_embed.set_image(url=slot_image)

                    for member in role.members:
                        try:
                            await member.send("⏰ **Event Reminder – Today!**")
                            await member.send(embed=main_embed)

                            if route_embed:
                                await member.send(embed=route_embed)

                            await member.send(embed=slot_embed)
                        except:
                            pass
            except:
                continue

    # -----------------------------------------------------
    # AUTO DELETE PAST EVENTS
    # -----------------------------------------------------
    @tasks.loop(hours=6)
    async def cleanup_loop(self):
        today = datetime.now(IST).date()

        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "DELETE FROM events WHERE event_date < ?",
                (today.strftime("%Y-%m-%d"),)
            )
            await db.commit()

    # -----------------------------------------------------
    @reminder_loop.before_loop
    @cleanup_loop.before_loop
    @calendar_loop.before_loop
    async def before_loops(self):
        await self.bot.wait_until_ready()
        await self.init_db()


# =========================================================
# SETUP
# =========================================================

async def setup(bot: commands.Bot):
    await bot.add_cog(TruckersMPEvents(bot))
