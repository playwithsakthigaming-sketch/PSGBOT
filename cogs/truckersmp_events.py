import discord
import aiosqlite
import aiohttp
import requests
import calendar
import re
from bs4 import BeautifulSoup
from datetime import datetime
from discord.ext import commands, tasks
from discord import app_commands

DB_NAME = "bot.db"
TRUCKERSMP_API = "https://api.truckersmp.com/v2/events/"
TRUCKERSMP_EVENT_PAGE = "https://truckersmp.com/events/"


# ================= DATABASE =================
async def init_event_table():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS tmp_events (
            guild_id INTEGER PRIMARY KEY,
            event_id INTEGER,
            channel_id INTEGER,
            role_id INTEGER,
            slot_number TEXT,
            slot_image TEXT,
            last_reminder INTEGER DEFAULT 0
        )
        """)
        await db.commit()


# ================= API FETCH =================
async def fetch_event(event_id: int):
    url = TRUCKERSMP_API + str(event_id)
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=15) as r:
            if r.status != 200:
                return None
            data = await r.json()
            return data.get("response")


# ================= SCRAPE ROUTE IMAGE =================
def fetch_route_image(event_url: str):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(event_url, headers=headers, timeout=15)
        soup = BeautifulSoup(res.text, "html.parser")

        img = soup.find("img", {"class": "img-fluid"})
        if img and img.get("src"):
            return img["src"]

    except Exception as e:
        print("Route fetch error:", e)

    return None


# ================= IMAGE HELPERS =================
def fix_imgur_url(url: str):
    if not url:
        return None
    if "imgur.com" in url and "i.imgur.com" not in url:
        code = url.split("/")[-1]
        return f"https://i.imgur.com/{code}"
    return url


def extract_image_from_markdown(text: str):
    if not text:
        return None, text

    match = re.search(r'!\[.*?\]\((https?://[^\s)]+)\)', text)
    if match:
        image_url = fix_imgur_url(match.group(1))
        clean_text = re.sub(r'!\[.*?\]\(.*?\)', '', text).strip()
        return image_url, clean_text

    return None, text


# ================= EMBED BUILDERS =================
def build_event_embed(event):
    description = event.get("description", "No description")
    image_url, clean_description = extract_image_from_markdown(description)

    event_url = f"{TRUCKERSMP_EVENT_PAGE}{event['id']}"

    embed = discord.Embed(
        title=event["name"],
        url=event_url,
        description=clean_description or "No description",
        color=discord.Color.orange()
    )

    start = event["start_at"]
    embed.add_field(name="📅 Date", value=start[:10])
    embed.add_field(name="🕒 Time", value=start[11:16])

    if image_url:
        embed.set_image(url=image_url)

    embed.set_footer(text="TruckersMP Event System")
    return embed


# ================= ROUTE IMAGE LOGIC =================
def build_route_embed(event):
    route_img = None

    # 1. Official API route image
    if event.get("route") and isinstance(event["route"], dict):
        route_img = event["route"].get("image")

    # 2. Backup API field
    if not route_img:
        route_img = event.get("route_image")

    # 3. Scrape from event webpage
    if not route_img:
        event_url = f"{TRUCKERSMP_EVENT_PAGE}{event['id']}"
        route_img = fetch_route_image(event_url)

    # 4. Fallback from description
    if not route_img:
        desc = event.get("description", "")
        match = re.search(r'!\[.*?\]\((https?://[^\s)]+)\)', desc)
        if match:
            route_img = match.group(1)

    route_img = fix_imgur_url(route_img)

    if not route_img:
        return None

    embed = discord.Embed(
        title="🗺 Event Route",
        color=discord.Color.blue()
    )
    embed.set_image(url=route_img)
    embed.set_footer(text="Route from TruckersMP")
    return embed


def build_slot_embed(slot_number, slot_image):
    embed = discord.Embed(
        title="🚚 Slot Information",
        color=discord.Color.green()
    )

    embed.add_field(
        name="🎯 Slot Number",
        value=slot_number or "N/A",
        inline=False
    )

    if slot_image:
        embed.set_image(url=fix_imgur_url(slot_image))

    return embed


# ================= CALENDAR =================
def build_month_view(event, year, month):
    event_time = datetime.fromisoformat(
        event["start_at"].replace("Z", "")
    )

    event_day = event_time.day if (
        event_time.year == year and event_time.month == month
    ) else None

    cal = calendar.monthcalendar(year, month)
    calendar_text = " Mo  Tu  We  Th  Fr  Sa  Su\n"

    for week in cal:
        for day in week:
            if day == 0:
                calendar_text += "    "
            elif day == event_day:
                calendar_text += " 🚚 "
            else:
                calendar_text += f" {str(day).rjust(2)} "
        calendar_text += "\n"

    embed = discord.Embed(
        title=f"📅 {calendar.month_name[month]} {year}",
        description=f"**{event['name']}**",
        color=discord.Color.gold()
    )

    embed.add_field(
        name="Event Calendar",
        value=f"```{calendar_text}```",
        inline=False
    )

    embed.set_footer(text="🚚 = Event Day")
    return embed


# ================= BUTTON VIEW =================
class EventButtonView(discord.ui.View):
    def __init__(self, event_id):
        super().__init__(timeout=None)
        event_url = f"{TRUCKERSMP_EVENT_PAGE}{event_id}"

        self.add_item(
            discord.ui.Button(
                label="I Will Be There",
                url=event_url,
                style=discord.ButtonStyle.link,
                emoji="✅"
            )
        )


# ================= COG =================
class TMPEvents(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.reminder_loop.start()

    async def cog_load(self):
        await init_event_table()

    @app_commands.command(name="event", description="Setup TruckersMP event")
    async def event(
        self,
        interaction: discord.Interaction,
        event_url: str,
        channel: discord.TextChannel,
        role: discord.Role,
        slot_number: str,
        slot_image: str = None
    ):
        await interaction.response.defer()

        try:
            event_id = int(event_url.split("/")[-1])
        except:
            return await interaction.followup.send("❌ Invalid event URL")

        event = await fetch_event(event_id)
        if not event:
            return await interaction.followup.send("❌ Event not found")

        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("""
            INSERT OR REPLACE INTO tmp_events
            (guild_id, event_id, channel_id, role_id,
             slot_number, slot_image)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (
                interaction.guild.id,
                event_id,
                channel.id,
                role.id,
                slot_number,
                slot_image
            ))
            await db.commit()

        await interaction.followup.send("✅ Event saved")
        await self.post_event(interaction.guild.id)

    async def post_event(self, guild_id):
        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute("""
            SELECT event_id, channel_id, role_id,
                   slot_number, slot_image
            FROM tmp_events WHERE guild_id=?
            """, (guild_id,))
            row = await cur.fetchone()

        if not row:
            return

        event_id, channel_id, role_id, slot_number, slot_image = row
        event = await fetch_event(event_id)
        if not event:
            return

        guild = self.bot.get_guild(guild_id)
        if not guild:
            return

        channel = guild.get_channel(channel_id)
        if not channel:
            return

        role = guild.get_role(role_id)

        await channel.send(
            content=role.mention if role else None,
            embed=build_event_embed(event),
            view=EventButtonView(event_id)
        )

        route_embed = build_route_embed(event)
        if route_embed:
            await channel.send(embed=route_embed)

        await channel.send(embed=build_slot_embed(slot_number, slot_image))

    @tasks.loop(minutes=10)
    async def reminder_loop(self):
        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute("SELECT guild_id FROM tmp_events")
            rows = await cur.fetchall()

        for (guild_id,) in rows:
            await self.post_event(guild_id)


# ================= SETUP =================
async def setup(bot: commands.Bot):
    await bot.add_cog(TMPEvents(bot))
