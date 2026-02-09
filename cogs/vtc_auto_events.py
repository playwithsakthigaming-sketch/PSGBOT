import discord
import requests
import aiosqlite
import re
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime

DB_NAME = "vtc_events.db"
API_VTC_EVENTS = "https://api.truckersmp.com/v2/vtc/{}/events"


class VTCAutoEvents(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.sync_events.start()

    def cog_unload(self):
        self.sync_events.cancel()

    # ================= DATABASE SETUP =================
    async def init_db(self):
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    guild_id INTEGER PRIMARY KEY,
                    vtc_id INTEGER,
                    channel_id INTEGER
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS posted_events (
                    event_id INTEGER PRIMARY KEY
                )
            """)
            await db.commit()

    async def is_posted(self, event_id: int):
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute(
                "SELECT event_id FROM posted_events WHERE event_id=?",
                (event_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return row is not None

    async def mark_posted(self, event_id: int):
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "INSERT OR IGNORE INTO posted_events(event_id) VALUES(?)",
                (event_id,)
            )
            await db.commit()

    # ================= COMMAND =================
    @app_commands.command(
        name="setvtc",
        description="Set VTC ID and channel for auto event sync"
    )
    async def setvtc(
        self,
        interaction: discord.Interaction,
        vtc_id: int,
        channel: discord.TextChannel
    ):
        await self.init_db()

        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("""
                INSERT OR REPLACE INTO settings(guild_id, vtc_id, channel_id)
                VALUES(?, ?, ?)
            """, (interaction.guild.id, vtc_id, channel.id))
            await db.commit()

        await interaction.response.send_message(
            f"✅ Auto-sync enabled for VTC **{vtc_id}** in {channel.mention}"
        )

    # ================= AUTO SYNC LOOP =================
    @tasks.loop(minutes=1)
    async def sync_events(self):
        await self.init_db()

        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute(
                "SELECT guild_id, vtc_id, channel_id FROM settings"
            ) as cursor:
                rows = await cursor.fetchall()

        for guild_id, vtc_id, channel_id in rows:
            try:
                response = requests.get(
                    API_VTC_EVENTS.format(vtc_id),
                    timeout=10
                )
                data = response.json()

                if not data.get("response"):
                    continue

                events = data["response"]
                channel = self.bot.get_channel(channel_id)

                if not channel:
                    continue

                for event in events:
                    event_id = event["id"]

                    # Only attending events
                    if not event.get("attending"):
                        continue

                    if await self.is_posted(event_id):
                        continue

                    name = event["name"]
                    description = event.get("description", "No description")
                    banner = event.get("banner")
                    route_map = event.get("map")
                    start = event["start_at"]
                    url = event["url"]
                    vtc_logo = event.get("vtc", {}).get("logo")

                    # Fix URLs
                    def fix_url(u):
                        if u and u.startswith("/"):
                            return "https://truckersmp.com" + u
                        return u

                    url = fix_url(url)
                    banner = fix_url(banner)
                    route_map = fix_url(route_map)
                    vtc_logo = fix_url(vtc_logo)

                    # Extract image from description
                    img_match = re.search(r'!\[\]\((.*?)\)', description)
                    extracted_image = None

                    if img_match:
                        extracted_image = img_match.group(1)
                        description = re.sub(
                            r'!\[\]\(.*?\)',
                            '',
                            description
                        ).strip()

                    start_time = datetime.fromisoformat(
                        start.replace("Z", "+00:00")
                    )

                    embed = discord.Embed(
                        title=name,
                        description=description,
                        url=url,
                        color=discord.Color.orange()
                    )

                    embed.add_field(
                        name="Start Time",
                        value=f"<t:{int(start_time.timestamp())}:F>",
                        inline=False
                    )

                    # MAIN IMAGE (priority: route → banner → extracted)
                    if route_map:
                        embed.set_image(url=route_map)
                    elif banner:
                        embed.set_image(url=banner)
                    elif extracted_image:
                        embed.set_image(url=extracted_image)

                    # VTC logo as thumbnail
                    if vtc_logo:
                        embed.set_thumbnail(url=vtc_logo)

                    embed.set_footer(text="VTC Attending Event")

                    await channel.send(embed=embed)
                    await self.mark_posted(event_id)

            except Exception as e:
                print(f"Sync error for guild {guild_id}:", e)

    @sync_events.before_loop
    async def before_sync(self):
        await self.bot.wait_until_ready()
        await self.init_db()


# ================= SETUP =================
async def setup(bot: commands.Bot):
    await bot.add_cog(VTCAutoEvents(bot))
