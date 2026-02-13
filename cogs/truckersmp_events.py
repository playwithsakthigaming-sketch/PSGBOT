import discord
import aiohttp
import re
import os
from datetime import datetime, timedelta, timezone
from discord.ext import commands, tasks
from discord import app_commands
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# =========================
# LOAD ENV
# =========================
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}

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

                # Method 1: Normal <img>
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

                # Method 2: Markdown image
                text = soup.get_text()
                match = re.search(r'![](()', text)
                if match:
                    return match.group(1)

    except Exception as e:
        print("Route image error:", e)

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

    # -----------------------------------------------------
    # SUPABASE HELPERS
    # -----------------------------------------------------
    async def insert_event(self, event_id, guild_id, role_id, event_date):
        payload = {
            "event_id": event_id,
            "guild_id": guild_id,
            "role_id": role_id,
            "event_date": event_date
        }

        async with aiohttp.ClientSession() as session:
            await session.post(
                f"{SUPABASE_URL}/rest/v1/events",
                headers=HEADERS,
                json=payload
            )

    async def fetch_events(self):
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{SUPABASE_URL}/rest/v1/events",
                headers=HEADERS
            ) as res:
                return await res.json()

    async def delete_event(self, event_id):
        async with aiohttp.ClientSession() as session:
            await session.delete(
                f"{SUPABASE_URL}/rest/v1/events?event_id=eq.{event_id}",
                headers=HEADERS
            )

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

        dt_utc = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        dt_ist = dt_utc.astimezone(IST)
        event_date = dt_ist.strftime("%Y-%m-%d")

        route_image = await fetch_route_image(url)

        embed = discord.Embed(title=title, url=url, description=description)
        embed.add_field(name="Server", value=server)
        embed.add_field(name="Date", value=dt_ist.strftime("%d %b %Y"))
        embed.add_field(name="Time", value=dt_ist.strftime("%H:%M"))

        if banner:
            embed.set_image(url=banner)

        await channel.send(role.mention)
        await channel.send(embed=embed)

        if route_image:
            route_embed = discord.Embed(title="🗺 Route")
            route_embed.set_image(url=route_image)
            await channel.send(embed=route_embed)

        slot_embed = discord.Embed(title="🚚 Slot Info")
        slot_embed.add_field(name="Slot", value=str(slot_number))
        if slot_image:
            slot_embed.set_image(url=slot_image)

        await channel.send(embed=slot_embed)

        await self.insert_event(event_id, interaction.guild.id, role.id, event_date)
        await interaction.followup.send("✅ Event posted and saved.")

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
        embed = discord.Embed(title="📅 Event Calendar", color=discord.Color.orange())
        rows = await self.fetch_events()

        if not rows:
            embed.description = "No upcoming events."
            return embed

        lines = []
        for row in rows:
            event_id = row["event_id"]
            event_date = row["event_date"]
            dt = datetime.strptime(event_date, "%Y-%m-%d")
            formatted = dt.strftime("%d %b %Y")
            url = f"https://truckersmp.com/events/{event_id}"
            lines.append(f"**{formatted}** → [Event Link]({url})")

        embed.description = "\n".join(lines)
        return embed

    # -----------------------------------------------------
    # LOOPS
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

    @tasks.loop(minutes=30)
    async def reminder_loop(self):
        now_ist = datetime.now(IST)
        rows = await self.fetch_events()

        for row in rows:
            event_id = row["event_id"]
            guild_id = row["guild_id"]
            role_id = row["role_id"]
            event_date = row["event_date"]

            try:
                event_day = datetime.strptime(event_date, "%Y-%m-%d").date()

                if now_ist.date() == event_day and now_ist.hour == 7:
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

    @tasks.loop(hours=6)
    async def cleanup_loop(self):
        today = datetime.now(IST).date()
        rows = await self.fetch_events()

        for row in rows:
            event_id = row["event_id"]
            event_date = row["event_date"]

            try:
                event_day = datetime.strptime(event_date, "%Y-%m-%d").date()
                if event_day < today:
                    await self.delete_event(event_id)
            except:
                continue


# =========================================================
# SETUP
# =========================================================

async def setup(bot: commands.Bot):
    await bot.add_cog(TruckersMPEvents(bot))
