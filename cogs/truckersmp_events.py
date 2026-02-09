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
        self.reminder_loop.start()

    def cog_unload(self):
        self.reminder_loop.cancel()

    async def init_db(self):
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    event_id INTEGER,
                    guild_id INTEGER,
                    channel_id INTEGER,
                    message_ids TEXT,
                    event_date TEXT,
                    end_date TEXT,
                    reminded INTEGER DEFAULT 0
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    guild_id INTEGER PRIMARY KEY,
                    reminder_role INTEGER
                )
            """)
            await db.commit()

    # -----------------------------------------------------
    # SET REMINDER ROLE
    # -----------------------------------------------------
    @app_commands.command(name="setreminderrole", description="Set role for event reminders")
    async def setreminderrole(self, interaction: discord.Interaction, role: discord.Role):
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "INSERT OR REPLACE INTO settings (guild_id, reminder_role) VALUES (?, ?)",
                (interaction.guild.id, role.id)
            )
            await db.commit()

        await interaction.response.send_message(
            f"✅ Reminder role set to {role.mention}"
        )

    # -----------------------------------------------------
    # EVENT COMMAND
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
        end_time = data["end_at"]
        server = data["server"]["name"]
        url = f"https://truckersmp.com/events/{event_id}"

        start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))

        event_date = start_dt.strftime("%Y-%m-%d")
        end_date = end_dt.strftime("%Y-%m-%d")

        route_image = await fetch_route_image(url)

        embed = discord.Embed(
            title=title,
            url=url,
            description=description,
            color=discord.Color.blue()
        )
        embed.add_field(name="Server", value=server, inline=True)
        embed.add_field(name="Date", value=start_dt.strftime("%d %b %Y"), inline=True)
        embed.add_field(name="Time (UTC)", value=start_dt.strftime("%H:%M"), inline=True)

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

        # Send messages
        sent_ids = []
        await channel.send(role.mention)

        msg = await channel.send(embed=embed)
        sent_ids.append(msg.id)

        if route_embed:
            msg = await channel.send(embed=route_embed)
            sent_ids.append(msg.id)

        msg = await channel.send(embed=slot_embed)
        sent_ids.append(msg.id)

        # Save event
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("""
                INSERT INTO events 
                (event_id, guild_id, channel_id, message_ids, event_date, end_date, reminded)
                VALUES (?, ?, ?, ?, ?, ?, 0)
            """, (
                event_id,
                interaction.guild.id,
                channel.id,
                ",".join(map(str, sent_ids)),
                event_date,
                end_date
            ))
            await db.commit()

        await interaction.followup.send("✅ Event posted and reminder scheduled.")

    # -----------------------------------------------------
    # UPCOMING EVENTS
    # -----------------------------------------------------
    @app_commands.command(name="upcomingevents", description="Show upcoming events")
    async def upcomingevents(self, interaction: discord.Interaction):
        today = datetime.utcnow().date()

        async with aiosqlite.connect(DB_NAME) as db:
            rows = await db.execute_fetchall(
                "SELECT event_id, event_date FROM events WHERE guild_id=?",
                (interaction.guild.id,)
            )

        future_events = []
        for event_id, event_date in rows:
            date_obj = datetime.strptime(event_date, "%Y-%m-%d").date()
            if date_obj >= today:
                future_events.append((event_id, date_obj))

        if not future_events:
            return await interaction.response.send_message(
                "No upcoming events.", ephemeral=True
            )

        future_events.sort(key=lambda x: x[1])

        embed = discord.Embed(
            title="📅 Upcoming Events",
            color=discord.Color.blue()
        )

        for event_id, date_obj in future_events:
            embed.add_field(
                name=f"Event {event_id}",
                value=f"{date_obj.strftime('%d %b %Y')}\n"
                      f"https://truckersmp.com/events/{event_id}",
                inline=False
            )

        await interaction.response.send_message(embed=embed)

    # -----------------------------------------------------
    # REMINDER + CLEANUP LOOP
    # -----------------------------------------------------
    @tasks.loop(minutes=15)
    async def reminder_loop(self):
        now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
        now_ist = now_utc.astimezone(IST)

        async with aiosqlite.connect(DB_NAME) as db:
            events = await db.execute_fetchall("SELECT * FROM events")
            settings = await db.execute_fetchall("SELECT * FROM settings")

        settings_dict = {g: r for g, r in settings}

        for event in events:
            event_id, guild_id, channel_id, message_ids, event_date, end_date, reminded = event

            try:
                event_day = datetime.strptime(event_date, "%Y-%m-%d").date()
                end_day = datetime.strptime(end_date, "%Y-%m-%d").date()

                guild = self.bot.get_guild(guild_id)
                if not guild:
                    continue

                # Reminder
                reminder_role_id = settings_dict.get(guild_id)
                if (
                    reminder_role_id
                    and not reminded
                    and now_ist.date() == event_day
                    and now_ist.hour == 7
                ):
                    role = guild.get_role(reminder_role_id)
                    if role:
                        for member in role.members:
                            try:
                                await member.send(
                                    f"⏰ Reminder: Event today!\n"
                                    f"https://truckersmp.com/events/{event_id}"
                                )
                            except:
                                pass

                    async with aiosqlite.connect(DB_NAME) as db:
                        await db.execute(
                            "UPDATE events SET reminded=1 WHERE event_id=? AND guild_id=?",
                            (event_id, guild_id)
                        )
                        await db.commit()

                # Auto delete after end
                if now_ist.date() > end_day:
                    channel = guild.get_channel(channel_id)
                    if channel:
                        for mid in message_ids.split(","):
                            try:
                                msg = await channel.fetch_message(int(mid))
                                await msg.delete()
                            except:
                                pass

                    async with aiosqlite.connect(DB_NAME) as db:
                        await db.execute(
                            "DELETE FROM events WHERE event_id=? AND guild_id=?",
                            (event_id, guild_id)
                        )
                        await db.commit()

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
