import discord
import aiosqlite
import requests
import calendar
import re
from datetime import datetime
from discord.ext import commands, tasks
from discord import app_commands

DB_NAME = "bot.db"
TRUCKERSMP_API = "https://api.truckersmp.com/v2/events/"


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
def fetch_event(event_id: int):
    url = TRUCKERSMP_API + str(event_id)
    r = requests.get(url, timeout=15)
    if r.status_code != 200:
        return None
    return r.json().get("response")


# ================= IMAGE EXTRACT =================
def extract_image_from_markdown(text: str):
    if not text:
        return None, text

    match = re.search(r'!\[.*?\]\((https?://[^\s)]+)\)', text)
    if match:
        image_url = match.group(1)
        clean_text = re.sub(r'!\[.*?\]\(.*?\)', '', text).strip()
        return image_url, clean_text

    return None, text


# ================= EMBED BUILDERS =================
def build_event_embed(event):
    description = event.get("description", "No description")
    image_url, clean_description = extract_image_from_markdown(description)

    embed = discord.Embed(
        title=event["name"],
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


# FIXED ROUTE IMAGE FETCH
def build_route_embed(event):
    route_img = None

    # Primary location
    if event.get("route"):
        route_img = event["route"].get("image")

    # Fallback location (some TMP events use this)
    if not route_img:
        route_img = event.get("route_image")

    if not route_img:
        return None

    embed = discord.Embed(
        title="🗺 Route Map",
        color=discord.Color.blue()
    )
    embed.set_image(url=route_img)
    return embed


# SLOT EMBED (separate)
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


# ================= COG =================
class TMPEvents(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.reminder_loop.start()

    async def cog_load(self):
        await init_event_table()

    # ---------------- /EVENT ----------------
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

        event = fetch_event(event_id)
        if not event:
            return await interaction.followup.send("❌ Event not found")

        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("""
            INSERT OR REPLACE INTO tmp_events
            (guild_id, event_id, channel_id, role_id, slot_number, slot_image)
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

    # ---------------- POST EVENT ----------------
    async def post_event(self, guild_id):
        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute("""
            SELECT event_id, channel_id, role_id, slot_number, slot_image
            FROM tmp_events WHERE guild_id=?
            """, (guild_id,))
            row = await cur.fetchone()

        if not row:
            return

        event_id, channel_id, role_id, slot_number, slot_image = row
        event = fetch_event(event_id)
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
        embed = build_event_embed(event)
        await channel.send(content=role.mention if role else None, embed=embed)

        # Route embed
        route_embed = build_route_embed(event)
        if route_embed:
            await channel.send(embed=route_embed)

        # Slot embed (always send)
        slot_embed = build_slot_embed(slot_number, slot_image)
        await channel.send(embed=slot_embed)

    # ---------------- REMINDER LOOP ----------------
    @tasks.loop(minutes=10)
    async def reminder_loop(self):
        now = datetime.utcnow()

        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute("""
            SELECT guild_id, event_id, role_id, last_reminder
            FROM tmp_events
            """)
            rows = await cur.fetchall()

        for guild_id, event_id, role_id, last_reminder in rows:
            event = fetch_event(event_id)
            if not event:
                continue

            event_time = datetime.fromisoformat(
                event["start_at"].replace("Z", "")
            )
            reminder_time = event_time.replace(hour=7, minute=0, second=0)

            if now >= reminder_time:
                if last_reminder and last_reminder > int(reminder_time.timestamp()):
                    continue

                guild = self.bot.get_guild(guild_id)
                if not guild:
                    continue

                role = guild.get_role(role_id)
                if not role:
                    continue

                for member in role.members:
                    try:
                        await member.send(
                            f"🚚 Reminder: Event **{event['name']}** is today!"
                        )
                    except:
                        pass

                async with aiosqlite.connect(DB_NAME) as db:
                    await db.execute("""
                    UPDATE tmp_events
                    SET last_reminder=?
                    WHERE guild_id=?
                    """, (int(now.timestamp()), guild_id))
                    await db.commit()

    @reminder_loop.before_loop
    async def before_loops(self):
        await self.bot.wait_until_ready()


# ================= SETUP =================
async def setup(bot: commands.Bot):
    await bot.add_cog(TMPEvents(bot))
