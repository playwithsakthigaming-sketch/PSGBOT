import discord
import aiosqlite
import requests
import calendar
import re
from datetime import datetime, timezone
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

    match = re.search(r'!\[\]\((.*?)\)', text)
    if match:
        image_url = match.group(1)
        clean_text = re.sub(r'!\[\]\(.*?\)', '', text).strip()
        return image_url, clean_text

    return None, text


# ================= EMBED BUILDERS =================
def build_event_embed(event, slot_number):
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
    embed.add_field(name="🎯 Slot", value=slot_number or "N/A")

    if image_url:
        embed.set_image(url=image_url)

    embed.set_footer(text="TruckersMP Event System")
    return embed


def build_route_embed(event):
    route_img = event.get("route", {}).get("image")
    if not route_img:
        return None

    embed = discord.Embed(
        title="🗺 Route Map",
        color=discord.Color.blue()
    )
    embed.set_image(url=route_img)
    return embed


def build_slot_embed(slot_image):
    if not slot_image:
        return None

    embed = discord.Embed(
        title="🚚 Slot Image",
        color=discord.Color.green()
    )
    embed.set_image(url=slot_image)
    return embed


def build_month_view(event, slot_number, year, month):
    event_time = datetime.fromisoformat(
        event["start_at"].replace("Z", "")
    )

    event_day = event_time.day if (
        event_time.year == year and event_time.month == month
    ) else None

    cal = calendar.monthcalendar(year, month)
    calendar_text = "Mo Tu We Th Fr Sa Su\n"

    for week in cal:
        for day in week:
            if day == 0:
                calendar_text += "   "
            elif day == event_day:
                calendar_text += "🚚 "
            else:
                calendar_text += f"{str(day).rjust(2)} "
        calendar_text += "\n"

    embed = discord.Embed(
        title=f"📅 {calendar.month_name[month]} {year}",
        description=f"**{event['name']}**",
        color=discord.Color.gold()
    )

    embed.add_field(
        name="Calendar",
        value=f"```{calendar_text}```",
        inline=False
    )

    embed.set_footer(text="🚚 = Event Day")
    return embed


# ================= CALENDAR UI =================
class CalendarView(discord.ui.View):
    def __init__(self, event, slot_number, slot_image, year, month):
        super().__init__(timeout=300)
        self.event = event
        self.slot_number = slot_number
        self.slot_image = slot_image
        self.year = year
        self.month = month
        self.update_buttons()

    def update_buttons(self):
        self.clear_items()

        self.add_item(CalendarNavButton("◀", -1))

        event_time = datetime.fromisoformat(
            self.event["start_at"].replace("Z", "")
        )
        if event_time.year == self.year and event_time.month == self.month:
            self.add_item(EventDayButton(event_time.day))

        self.add_item(CalendarNavButton("▶", 1))


class CalendarNavButton(discord.ui.Button):
    def __init__(self, label, direction):
        super().__init__(label=label, style=discord.ButtonStyle.secondary)
        self.direction = direction

    async def callback(self, interaction: discord.Interaction):
        view: CalendarView = self.view

        view.month += self.direction

        if view.month < 1:
            view.month = 12
            view.year -= 1
        elif view.month > 12:
            view.month = 1
            view.year += 1

        view.update_buttons()

        embed = build_month_view(
            view.event,
            view.slot_number,
            view.year,
            view.month
        )

        await interaction.response.edit_message(embed=embed, view=view)


class EventDayButton(discord.ui.Button):
    def __init__(self, day):
        super().__init__(
            label=f"🚚 {day}",
            style=discord.ButtonStyle.success
        )

    async def callback(self, interaction: discord.Interaction):
        view: CalendarView = self.view
        event = view.event

        embed = build_event_embed(event, view.slot_number)
        await interaction.response.send_message(embed=embed, ephemeral=True)

        route_embed = build_route_embed(event)
        if route_embed:
            await interaction.followup.send(embed=route_embed, ephemeral=True)

        slot_embed = build_slot_embed(view.slot_image)
        if slot_embed:
            await interaction.followup.send(embed=slot_embed, ephemeral=True)


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

    # ---------------- /CALENDAR ----------------
    @app_commands.command(
        name="calendar",
        description="Interactive monthly calendar"
    )
    async def calendar(self, interaction: discord.Interaction):
        await interaction.response.defer()

        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute("""
            SELECT event_id, slot_number, slot_image
            FROM tmp_events
            WHERE guild_id=?
            """, (interaction.guild.id,))
            row = await cur.fetchone()

        if not row:
            return await interaction.followup.send("❌ No event set.")

        event_id, slot_number, slot_image = row
        event = fetch_event(event_id)
        if not event:
            return await interaction.followup.send("❌ Event not found.")

        event_time = datetime.fromisoformat(
            event["start_at"].replace("Z", "")
        )

        year = event_time.year
        month = event_time.month

        embed = build_month_view(event, slot_number, year, month)
        view = CalendarView(event, slot_number, slot_image, year, month)

        await interaction.followup.send(embed=embed, view=view)

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

        embed = build_event_embed(event, slot_number)
        await channel.send(content=role.mention if role else None, embed=embed)

        route_embed = build_route_embed(event)
        if route_embed:
            await channel.send(embed=route_embed)

        slot_embed = build_slot_embed(slot_image)
        if slot_embed:
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
