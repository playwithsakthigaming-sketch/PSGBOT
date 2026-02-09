import discord
import aiosqlite
import aiohttp
import time
from discord.ext import commands, tasks
from discord import app_commands
import re
from datetime import datetime

DB_NAME = "bot.db"
REMINDER_BEFORE = 3600  # 1 hour before event


# -----------------------------------------------------
# JOIN BUTTON
# -----------------------------------------------------
class JoinEventView(discord.ui.View):
    def __init__(self, event_link: str):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                label="I Will Be There",
                style=discord.ButtonStyle.link,
                url=event_link,
                emoji="🚛"
            )
        )


# -----------------------------------------------------
# EVENT COG
# -----------------------------------------------------
class EventSystem(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -----------------------------------------------------
    # ON READY
    # -----------------------------------------------------
    @commands.Cog.listener()
    async def on_ready(self):
        await self.init_db()

        if not self.reminder_loop.is_running():
            self.reminder_loop.start()

        if not self.update_loop.is_running():
            self.update_loop.start()

        if not self.countdown_loop.is_running():
            self.countdown_loop.start()

    # -----------------------------------------------------
    # DB INIT
    # -----------------------------------------------------
    async def init_db(self):
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT,
                    role_id INTEGER,
                    channel_id INTEGER,
                    slot_number INTEGER,
                    slot_image TEXT,
                    route_image TEXT,
                    start_time INTEGER,
                    reminded INTEGER DEFAULT 0,
                    message_id INTEGER,
                    created_by INTEGER
                )
            """)
            await db.commit()

    # -----------------------------------------------------
    # REMINDER LOOP
    # -----------------------------------------------------
    @tasks.loop(minutes=1)
    async def reminder_loop(self):
        now = int(time.time())

        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute("""
                SELECT event_id, role_id, channel_id, start_time
                FROM events
                WHERE reminded = 0
            """)
            rows = await cur.fetchall()

            for event_id, role_id, channel_id, start_time in rows:
                if start_time - now > REMINDER_BEFORE:
                    continue

                for guild in self.bot.guilds:
                    role = guild.get_role(role_id)
                    channel = guild.get_channel(channel_id)

                    if role and channel:
                        await channel.send(
                            f"🚛 {role.mention} **Convoy starting in 1 hour!**\n"
                            f"https://truckersmp.com/events/{event_id}"
                        )

                await db.execute(
                    "UPDATE events SET reminded = 1 WHERE event_id=?",
                    (event_id,)
                )

            await db.commit()

    # -----------------------------------------------------
    # AUTO UPDATE LOOP
    # -----------------------------------------------------
    @tasks.loop(minutes=10)
    async def update_loop(self):
        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute("""
                SELECT event_id, channel_id, message_id, role_id, slot_number
                FROM events
                WHERE message_id IS NOT NULL
            """)
            rows = await cur.fetchall()

        for event_id, channel_id, message_id, role_id, slot_number in rows:
            data = await self.fetch_event(event_id)
            if not data:
                continue

            name = data.get("name", "Unknown")
            start_str = data.get("start_at")
            server = data.get("server", {}).get("name", "Unknown")

            departure = data.get("departure") or {}
            dep_text = f"{departure.get('city','Unknown')} ({departure.get('location','Unknown')})"

            banner = data.get("banner")
            event_link = f"https://truckersmp.com/events/{event_id}"

            for guild in self.bot.guilds:
                channel = guild.get_channel(channel_id)
                role = guild.get_role(role_id)

                if not channel or not role:
                    continue

                try:
                    msg = await channel.fetch_message(message_id)
                except:
                    continue

                embed = discord.Embed(
                    title=f"🚛 {name}",
                    url=event_link,
                    color=discord.Color.orange(),
                    description=role.mention
                )

                embed.add_field(name="📅 Date", value=start_str, inline=True)
                embed.add_field(name="🖥 Server", value=server, inline=True)
                embed.add_field(name="🅿 Slot", value=str(slot_number), inline=True)
                embed.add_field(name="📍 Departure", value=dep_text, inline=False)

                if banner:
                    embed.set_image(url=banner)

                await msg.edit(embed=embed)

    # -----------------------------------------------------
    # COUNTDOWN LOOP
    # -----------------------------------------------------
    @tasks.loop(minutes=1)
    async def countdown_loop(self):
        now = int(time.time())

        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute("""
                SELECT event_id, channel_id, message_id, role_id,
                       slot_number, start_time
                FROM events
                WHERE message_id IS NOT NULL
            """)
            rows = await cur.fetchall()

        for event_id, channel_id, message_id, role_id, slot_number, start_time in rows:
            if not start_time or start_time < now:
                continue

            remaining = start_time - now
            days = remaining // 86400
            hours = (remaining % 86400) // 3600
            minutes = (remaining % 3600) // 60
            countdown = f"{days}d {hours}h {minutes}m"

            data = await self.fetch_event(event_id)
            if not data:
                continue

            name = data.get("name", "Unknown")
            server = data.get("server", {}).get("name", "Unknown")
            start_str = data.get("start_at")
            departure = data.get("departure") or {}

            dep_text = f"{departure.get('city','Unknown')} ({departure.get('location','Unknown')})"
            banner = data.get("banner")
            event_link = f"https://truckersmp.com/events/{event_id}"

            for guild in self.bot.guilds:
                channel = guild.get_channel(channel_id)
                role = guild.get_role(role_id)

                if not channel or not role:
                    continue

                try:
                    msg = await channel.fetch_message(message_id)
                except:
                    continue

                embed = discord.Embed(
                    title=f"🚛 {name}",
                    url=event_link,
                    color=discord.Color.orange(),
                    description=f"{role.mention}\n⏳ **Starts in:** {countdown}"
                )

                embed.add_field(name="📅 Date", value=start_str, inline=True)
                embed.add_field(name="🖥 Server", value=server, inline=True)
                embed.add_field(name="🅿 Slot", value=str(slot_number), inline=True)
                embed.add_field(name="📍 Departure", value=dep_text, inline=False)

                if banner:
                    embed.set_image(url=banner)

                embed.set_footer(text="Live countdown")

                await msg.edit(embed=embed)

    # -----------------------------------------------------
    # HELPERS
    # -----------------------------------------------------
    def extract_event_id(self, text: str) -> str:
        match = re.search(r"(\d+)", text)
        return match.group(1) if match else text

    async def fetch_event(self, event_id: str):
        url = f"https://api.truckersmp.com/v2/events/{event_id}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                return data.get("response")

    # -----------------------------------------------------
    # /event (FULL DETAILS)
    # -----------------------------------------------------
    @app_commands.command(name="event", description="Create convoy event with full TruckersMP details")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def event(
        self,
        interaction: discord.Interaction,
        eventurl: str,
        role: discord.Role,
        channel: discord.TextChannel,
        slotnumber: int,
        slotimage: str,
        routeimage: str = None
    ):
        await interaction.response.defer()

        event_id = self.extract_event_id(eventurl)
        data = await self.fetch_event(event_id)

        if not data:
            return await interaction.followup.send("❌ Event not found.", ephemeral=True)

        name = data.get("name", "Unknown")
        start_str = data.get("start_at")
        server = data.get("server", {}).get("name", "Unknown")
        banner = data.get("banner")

        dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
        start_timestamp = int(dt.timestamp())

        departure = data.get("departure") or {}
        destination = data.get("arrival") or {}

        dep_text = f"{departure.get('city','Unknown')} ({departure.get('location','Unknown')})"

        dest_text = None
        if destination.get("city") or destination.get("location"):
            dest_text = f"{destination.get('city','Unknown')} ({destination.get('location','Unknown')})"

        api_route = data.get("map")
        final_route = routeimage if routeimage else api_route

        event_link = f"https://truckersmp.com/events/{event_id}"

        main_embed = discord.Embed(
            title=f"🚛 {name}",
            url=event_link,
            color=discord.Color.orange(),
            description=role.mention
        )

        main_embed.add_field(name="📅 Date", value=f"<t:{start_timestamp}:F>", inline=True)
        main_embed.add_field(name="🖥 Server", value=server, inline=True)
        main_embed.add_field(name="🅿 Slot", value=str(slotnumber), inline=True)
        main_embed.add_field(name="📍 Departure", value=dep_text, inline=False)

        if dest_text:
            main_embed.add_field(name="🏁 Destination", value=dest_text, inline=False)

        if banner:
            main_embed.set_image(url=banner)

        embeds = [main_embed]

        if final_route:
            route_embed = discord.Embed(title="🗺️ Event Route", color=discord.Color.blue())
            route_embed.set_image(url=final_route)
            embeds.append(route_embed)

        slot_embed = discord.Embed(title="🅿 Slot Information", color=discord.Color.green())
        slot_embed.set_image(url=slotimage)
        embeds.append(slot_embed)

        view = JoinEventView(event_link)
        msg = await interaction.followup.send(embeds=embeds, view=view)

        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("""
                INSERT INTO events (
                    event_id, role_id, channel_id,
                    slot_number, slot_image, route_image,
                    start_time, message_id, created_by
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event_id,
                role.id,
                channel.id,
                slotnumber,
                slotimage,
                final_route,
                start_timestamp,
                msg.id,
                interaction.user.id
            ))
            await db.commit()

    # -----------------------------------------------------
    # /event_calendar
    # -----------------------------------------------------
    @app_commands.command(name="event_calendar", description="View upcoming events")
    async def event_calendar(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        now = int(time.time())

        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute("""
                SELECT event_id, slot_number, start_time
                FROM events
                WHERE start_time > ?
                ORDER BY start_time ASC
                LIMIT 10
            """, (now,))
            rows = await cur.fetchall()

        if not rows:
            return await interaction.followup.send("No upcoming events.")

        embed = discord.Embed(title="📅 Upcoming Events", color=discord.Color.orange())

        for event_id, slot, start_time in rows:
            embed.add_field(
                name=f"Event {event_id}",
                value=f"<t:{start_time}:F>\nSlot: {slot}\nhttps://truckersmp.com/events/{event_id}",
                inline=False
            )

        await interaction.followup.send(embed=embed)

    # -----------------------------------------------------
    # /event_reminder_test
    # -----------------------------------------------------
    @app_commands.command(name="event_reminder_test", description="Send test reminder")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def event_reminder_test(self, interaction: discord.Interaction, event_id: str):
        await interaction.response.defer(ephemeral=True)

        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute("""
                SELECT role_id, channel_id
                FROM events
                WHERE event_id = ?
            """, (event_id,))
            row = await cur.fetchone()

        if not row:
            return await interaction.followup.send("❌ Event not found.")

        role = interaction.guild.get_role(row[0])
        channel = interaction.guild.get_channel(row[1])

        if role and channel:
            await channel.send(
                f"🧪 {role.mention} TEST REMINDER\n"
                f"https://truckersmp.com/events/{event_id}"
            )

        await interaction.followup.send("✅ Test reminder sent.")


# ---------------------------------------------------------
# SETUP
# ---------------------------------------------------------
async def setup(bot: commands.Bot):
    await bot.add_cog(EventSystem(bot))
