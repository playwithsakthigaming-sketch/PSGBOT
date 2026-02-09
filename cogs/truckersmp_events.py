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
        self.calendar_loop.start()
        self.cleanup_loop.start()

    def cog_unload(self):
        self.reminder_loop.cancel()
        self.calendar_loop.cancel()
        self.cleanup_loop.cancel()

    async def init_db(self):
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    event_id INTEGER,
                    guild_id INTEGER,
                    role_id INTEGER,
                    event_date TEXT
                )
            """)
            await db.commit()

    # -----------------------------------------------------
    # /event
    # -----------------------------------------------------
    @app_commands.command(name="event", description="Post a TruckersMP event")
    @app_commands.describe(
        event="Event URL or ID",
        channel="Channel to send event",
        role="Role to mention",
        slot_number="Slot number",
        slot_image="Slot image URL (optional)"
    )
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

        # Get VTC logo
        vtc_logo = None
        if data.get("vtc") and data["vtc"].get("logo"):
            vtc_logo = data["vtc"]["logo"]

        # Convert UTC → IST
        dt_utc = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        dt_ist = dt_utc.astimezone(IST)
        event_date = dt_ist.strftime("%Y-%m-%d")

        # Fetch route image
        route_image = await fetch_route_image(url)

        # ---------------- MAIN EVENT EMBED ----------------
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

        if vtc_logo:
            embed.set_thumbnail(url=vtc_logo)

        # ---------------- ROUTE EMBED ----------------
        route_embed = None
        if route_image:
            route_embed = discord.Embed(
                title="🗺 Event Route",
                color=discord.Color.green()
            )
            route_embed.set_image(url=route_image)

        # ---------------- SLOT EMBED ----------------
        slot_embed = discord.Embed(
            title="🚚 Slot Information",
            color=discord.Color.green()
        )
        slot_embed.add_field(name="Slot Number", value=str(slot_number))

        if slot_image:
            slot_embed.set_image(url=slot_image)

        # Send messages
        await channel.send(role.mention)
        await channel.send(embed=embed)

        if route_embed:
            await channel.send(embed=route_embed)

        await channel.send(embed=slot_embed)

        # Save event for reminder + calendar
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "INSERT INTO events VALUES (?, ?, ?, ?)",
                (event_id, interaction.guild.id, role.id, event_date)
            )
            await db.commit()

        await interaction.followup.send("✅ Event posted and reminder scheduled.")

    # (rest of code unchanged — calendar, reminder, cleanup, setup)
