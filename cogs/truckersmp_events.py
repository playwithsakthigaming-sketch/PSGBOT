import discord
import aiosqlite
import aiohttp
import re
from discord.ext import commands, tasks
from discord import app_commands
from bs4 import BeautifulSoup
from urllib.parse import urljoin

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


# ================= ROUTE IMAGE FETCH =================
async def fetch_route_image(event_id: int):
    event_url = f"{TRUCKERSMP_EVENT_PAGE}{event_id}"

    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        async with aiohttp.ClientSession() as session:
            async with session.get(event_url, headers=headers, timeout=15) as r:
                if r.status != 200:
                    return None

                html = await r.text()
                soup = BeautifulSoup(html, "html.parser")

                route_section = soup.find(
                    lambda tag: tag.name in ["h2", "h3", "h4"]
                    and "route" in tag.text.lower()
                )

                if route_section:
                    parent = route_section.find_parent()
                    if parent:
                        img = parent.find("img")
                        if img and img.get("src"):
                            return urljoin(event_url, img["src"])

                img = soup.select_one("img[src*='route']")
                if img and img.get("src"):
                    return urljoin(event_url, img["src"])

    except Exception as e:
        print("Route fetch error:", e)

    return None


# ================= DESCRIPTION CLEANER =================
def extract_convoy_info(text: str):
    if not text:
        return "No details available."

    # Remove markdown images
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text)

    lines = text.splitlines()
    convoy_lines = []

    for line in lines:
        line = line.strip()

        if re.match(r'^[•\-]\s*(Date|Server|Meetup|Departure|Route|Distance|Destination|Breaks|DLC|Event|Link)', line, re.IGNORECASE):
            clean = re.sub(r'^[•\-]\s*', '', line)
            convoy_lines.append(clean)

    if convoy_lines:
        return "\n".join(convoy_lines)

    return "No convoy details found."


# ================= EMBED BUILDERS =================
def build_event_embed(event):
    raw_description = event.get("description", "No description")
    clean_description = extract_convoy_info(raw_description)

    event_url = f"{TRUCKERSMP_EVENT_PAGE}{event['id']}"

    embed = discord.Embed(
        title=event["name"],
        url=event_url,
        description=clean_description,
        color=discord.Color.orange()
    )

    start = event["start_at"]
    embed.add_field(name="📅 Date", value=start[:10])
    embed.add_field(name="🕒 Time", value=start[11:16])

    embed.set_footer(text="TruckersMP Event System")
    return embed


def build_route_embed(route_image):
    embed = discord.Embed(
        title="🗺️ Event Route",
        color=discord.Color.blue()
    )
    embed.set_image(url=route_image)
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
        embed.set_image(url=slot_image)

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

        route_image = await fetch_route_image(event_id)

        guild = self.bot.get_guild(guild_id)
        if not guild:
            return

        channel = guild.get_channel(channel_id)
        role = guild.get_role(role_id)

        if not channel:
            return

        # Main event embed
        await channel.send(
            content=role.mention if role else None,
            embed=build_event_embed(event),
            view=EventButtonView(event_id)
        )

        # Route embed
        if route_image:
            await channel.send(embed=build_route_embed(route_image))

        # Slot embed
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
