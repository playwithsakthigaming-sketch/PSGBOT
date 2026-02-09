import discord
import aiosqlite
import aiohttp
import re
from datetime import datetime
from discord.ext import commands, tasks
from discord import app_commands
from bs4 import BeautifulSoup

DB_NAME = "events.db"
API_EVENT = "https://api.truckersmp.com/v2/events/{}"


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

                # Look for route section
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
        self.reminder_loop.start()

    def cog_unload(self):
        self.reminder_loop.cancel()

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
        url = f"https://truckersmp.com/events/{event_id}"

        dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        event_date = dt.strftime("%Y-%m-%d")

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
        embed.add_field(name="Date", value=dt.strftime("%d %b %Y"), inline=True)
        embed.add_field(name="Time (UTC)", value=dt.strftime("%H:%M"), inline=True)

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

        # Save event for reminder
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "INSERT INTO events VALUES (?, ?, ?, ?)",
                (event_id, interaction.guild.id, role.id, event_date)
            )
            await db.commit()

        await interaction.followup.send("✅ Event posted and reminder scheduled.")

    # -----------------------------------------------------
    # REMINDER LOOP
    # -----------------------------------------------------
    @tasks.loop(minutes=30)
    async def reminder_loop(self):
        now = datetime.utcnow()

        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT * FROM events") as cursor:
                rows = await cursor.fetchall()

        for event_id, guild_id, role_id, event_date in rows:
            try:
                event_day = datetime.strptime(event_date, "%Y-%m-%d").date()
                if now.date() == event_day and now.hour == 7:
                    guild = self.bot.get_guild(guild_id)
                    if not guild:
                        continue

                    role = guild.get_role(role_id)
                    if not role:
                        continue

                    for member in role.members:
                        try:
                            await member.send(
                                f"⏰ Reminder: Event today!\n"
                                f"https://truckersmp.com/events/{event_id}"
                            )
                        except:
                            pass
            except:
                continue

    @reminder_loop.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()
        await self.init_db()


# =========================================================
# SETUP
# =========================================================

async def setup(bot: commands.Bot):
    await bot.add_cog(TruckersMPEvents(bot))
