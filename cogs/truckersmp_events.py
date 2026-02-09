import discord
import aiosqlite
import aiohttp
import re
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
            manual_route TEXT,
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


# ================= ROUTE IMAGE LOGIC =================
def build_route_embed(event, manual_route):
    route_img = None

    # 1. Manual route image (highest priority)
    if manual_route:
        route_img = manual_route

    # 2. Official TruckersMP route map image only
    if not route_img and event.get("route"):
        route_img = event["route"].get("image")

    route_img = fix_imgur_url(route_img)

    if not route_img:
        return None

    embed = discord.Embed(
        title="🗺 Route Map",
        color=discord.Color.blue()
    )
    embed.set_image(url=route_img)
    embed.set_footer(text="Official TruckersMP Route Map")
    return embed


# ================= SLOT EMBED =================
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


# ================= EVENT EMBED =================
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
        slot_image: str = None,
        route_image: str = None
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
             slot_number, slot_image, manual_route)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                interaction.guild.id,
                event_id,
                channel.id,
                role.id,
                slot_number,
                slot_image,
                route_image
            ))
            await db.commit()

        await interaction.followup.send("✅ Event saved")
        await self.post_event(interaction.guild.id)

    async def post_event(self, guild_id):
        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute("""
            SELECT event_id, channel_id, role_id,
                   slot_number, slot_image, manual_route
            FROM tmp_events WHERE guild_id=?
            """, (guild_id,))
            row = await cur.fetchone()

        if not row:
            return

        event_id, channel_id, role_id, slot_number, slot_image, manual_route = row
        event = await fetch_event(event_id)
        if not event:
            return

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
        route_embed = build_route_embed(event, manual_route)
        if route_embed:
            await channel.send(embed=route_embed)

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
