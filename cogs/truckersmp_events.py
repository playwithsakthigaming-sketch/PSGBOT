import discord
import aiohttp
import re
import os
from datetime import datetime, timedelta, timezone
from discord.ext import commands, tasks
from discord import app_commands
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from collections import defaultdict

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

                # -----------------------------
                # METHOD 1: Normal <img> tag
                # -----------------------------
                for header in soup.find_all(["h2", "h3", "h4"]):
                    if "route" in header.text.lower():
                        section = header.find_next("div")
                        if section:
                            img = section.find("img")
                            if img and img.get("src"):
                                src = img["src"]
                                if src.startswith("/"):
                                    src = "https://truckersmp.com" + src
                                return fix_imgur(src)

                # -----------------------------
                # METHOD 2: Markdown images
                # -----------------------------
                match = re.search(r'!\[[^\]]*\]\((https?://[^\)]+)\)', html)
                if match:
                    return fix_imgur(match.group(1))

                # Broken format
                match = re.search(r'!\[\](https?://\S+)', html)
                if match:
                    return fix_imgur(match.group(1))

    except Exception as e:
        print("Route image error:", e)

    return None


# =============================
# IMGUR FIX
# =============================
def fix_imgur(url: str) -> str:
    if "imgur.com" in url and "i.imgur.com" not in url:
        url = url.replace("imgur.com", "i.imgur.com")
    return url


# =========================================================
# COG
# =========================================================

class TruckersMPEvents(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.calendar_message_id = None
        self.calendar_channel_id = None
        self.last_events_channel_id = None
        self.calendar_loop.start()
        self.cleanup_loop.start()

    def cog_unload(self):
        self.calendar_loop.cancel()
        self.cleanup_loop.cancel()

    # -----------------------------------------------------
    # SUPABASE HELPERS
    # -----------------------------------------------------
    async def insert_event(self, event_id, guild_id, role_id, event_date, title, time, server, slot):
        payload = {
            "event_id": event_id,
            "guild_id": guild_id,
            "role_id": role_id,
            "event_date": event_date,
            "title": title,
            "time": time,
            "server": server,
            "slot": slot
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
                f"{SUPABASE_URL}/rest/v1/events?order=event_date.asc",
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
    async def event(
        self,
        interaction: discord.Interaction,
        event: str,
        channel: discord.TextChannel,
        role: discord.Role,
        slot_number: int,
    ):
        await interaction.response.defer()

        event_id = extract_event_id(event)
        if not event_id:
            return await interaction.followup.send("❌ Invalid event link or ID.")

        data = await fetch_event(event_id)
        if not data:
            return await interaction.followup.send("❌ Event not found.")

        title = data["name"]
        start_time = data["start_at"]
        server = data["server"]["name"]
        url = f"https://truckersmp.com/events/{event_id}"

        dt_utc = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        dt_ist = dt_utc.astimezone(IST)
        event_date = dt_ist.strftime("%Y-%m-%d")
        time_str = dt_ist.strftime("%H:%M")

        # -------------------------
        # Upcoming event embed
        # -------------------------
        embed = discord.Embed(
            title="🚚 Upcoming Event",
            color=discord.Color.green()
        )
        embed.add_field(name="Event", value=title, inline=False)
        embed.add_field(name="Date", value=dt_ist.strftime("%d %b %Y"))
        embed.add_field(name="Time", value=time_str)
        embed.add_field(name="Server", value=server)
        embed.add_field(name="Slot", value=str(slot_number))
        embed.url = url

        await channel.send(role.mention)
        await channel.send(embed=embed)

        await self.insert_event(
            event_id,
            interaction.guild.id,
            role.id,
            event_date,
            title,
            time_str,
            server,
            slot_number
        )

        await interaction.followup.send("✅ Event posted.")

        await self.post_last_two_events()

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

        await interaction.followup.send("📅 Calendar created.")

    async def build_calendar_embed(self):
        embed = discord.Embed(title="📅 Event Calendar", color=discord.Color.orange())
        rows = await self.fetch_events()

        if not rows:
            embed.description = "No upcoming events."
            return embed

        grouped = defaultdict(list)

        for row in rows:
            dt = datetime.strptime(row["event_date"], "%Y-%m-%d")
            month_key = dt.strftime("%B %Y")
            grouped[month_key].append(row)

        desc = ""
        for month, events in grouped.items():
            desc += f"**{month}**\n"
            for e in events:
                dt = datetime.strptime(e["event_date"], "%Y-%m-%d")
                desc += f"{dt.strftime('%d %b')} – {e['title']}\n"
            desc += "\n"

        embed.description = desc
        return embed

    # -----------------------------------------------------
    # /deleteevent
    # -----------------------------------------------------
    @app_commands.command(name="deleteevent", description="Delete an event")
    async def deleteevent(self, interaction: discord.Interaction, event: str):
        await interaction.response.defer()

        event_id = extract_event_id(event)
        if not event_id:
            return await interaction.followup.send("❌ Invalid event ID.")

        await self.delete_event(event_id)
        await interaction.followup.send("🗑 Event deleted.")

    # -----------------------------------------------------
    # LAST 2 EVENTS CHANNEL
    # -----------------------------------------------------
    async def post_last_two_events(self):
        if not self.last_events_channel_id:
            return

        channel = self.bot.get_channel(self.last_events_channel_id)
        if not channel:
            return

        rows = await self.fetch_events()
        last_two = rows[-2:]

        await channel.purge(limit=10)

        for e in last_two:
            embed = discord.Embed(
                title=e["title"],
                color=discord.Color.blue()
            )
            embed.add_field(name="Date", value=e["event_date"])
            embed.add_field(name="Time", value=e["time"])
            embed.add_field(name="Server", value=e["server"])
            embed.add_field(name="Slot", value=str(e["slot"]))
            embed.url = f"https://truckersmp.com/events/{e['event_id']}"

            await channel.send(embed=embed)

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

    @tasks.loop(hours=6)
    async def cleanup_loop(self):
        today = datetime.now(IST).date()
        rows = await self.fetch_events()

        for row in rows:
            event_day = datetime.strptime(row["event_date"], "%Y-%m-%d").date()
            if event_day < today:
                await self.delete_event(row["event_id"])


# =========================================================
# SETUP
# =========================================================

async def setup(bot: commands.Bot):
    await bot.add_cog(TruckersMPEvents(bot))
