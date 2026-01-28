import discord
import aiohttp
import re
import os
import aiosqlite
from discord.ext import commands, tasks
from discord import app_commands

DB_NAME = "bot.db"
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

YOUTUBE_CHANNEL_REGEX = r"(?:youtube\.com\/(?:channel\/|@))([a-zA-Z0-9_-]+)"


# ================= HELPER =================
def extract_channel_id(url: str):
    match = re.search(YOUTUBE_CHANNEL_REGEX, url)
    if match:
        return match.group(1)
    return None


# ================= COG =================
class YouTubeAlerts(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_updates.start()

    def cog_unload(self):
        self.check_updates.cancel()

    # =================================================
    # /setup_channel
    # =================================================
    @app_commands.command(name="setup_channel", description="Add YouTube notifications")
    async def setup_channel(
        self,
        interaction: discord.Interaction,
        youtube_url: str,
        discord_channel: discord.TextChannel,
        role: discord.Role,
        message: str
    ):
        await interaction.response.defer(ephemeral=True)

        if not interaction.user.guild_permissions.administrator:
            return await interaction.followup.send("❌ Admin only.")

        channel_id = extract_channel_id(youtube_url)
        if not channel_id:
            return await interaction.followup.send("❌ Invalid YouTube URL.")

        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("""
                INSERT OR REPLACE INTO youtube_alerts
                (guild_id, youtube_channel, discord_channel, role_id, message, last_video)
                VALUES (?,?,?,?,?,?)
            """, (interaction.guild.id, channel_id, discord_channel.id, role.id, message, ""))
            await db.commit()

        await interaction.followup.send("✅ YouTube channel added successfully.")

    # =================================================
    # /remove_channel
    # =================================================
    @app_commands.command(name="remove_channel", description="Remove YouTube notifications")
    async def remove_channel(self, interaction: discord.Interaction, youtube_url: str):
        await interaction.response.defer(ephemeral=True)

        if not interaction.user.guild_permissions.administrator:
            return await interaction.followup.send("❌ Admin only.")

        channel_id = extract_channel_id(youtube_url)
        if not channel_id:
            return await interaction.followup.send("❌ Invalid YouTube URL.")

        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "DELETE FROM youtube_alerts WHERE guild_id=? AND youtube_channel=?",
                (interaction.guild.id, channel_id)
            )
            await db.commit()

        await interaction.followup.send("✅ YouTube channel removed.")

    # =================================================
    # /list_channels
    # =================================================
    @app_commands.command(name="list_channels", description="List all YouTube alert channels")
    async def list_channels(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute(
                "SELECT youtube_channel, discord_channel FROM youtube_alerts WHERE guild_id=?",
                (interaction.guild.id,)
            ) as cursor:
                rows = await cursor.fetchall()

        if not rows:
            return await interaction.followup.send("❌ No YouTube channels configured.")

        msg = ""
        for yt, dc in rows:
            msg += f"• `{yt}` → <#{dc}>\n"

        embed = discord.Embed(title="📺 YouTube Alert Channels", description=msg, color=discord.Color.blue())
        await interaction.followup.send(embed=embed)

    # =================================================
    # /test_youtube
    # =================================================
    @app_commands.command(name="test_youtube", description="Send test YouTube alert")
    async def test_youtube(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        embed = discord.Embed(
            title="🔴 TEST ALERT",
            description="This is a test YouTube notification.",
            color=discord.Color.red()
        )
        embed.add_field(name="Watch Here", value="https://youtube.com")

        await interaction.followup.send(embed=embed)

    # =================================================
    # CHECK LOOP (LIVE + SHORTS + VIDEOS)
    # =================================================
    @tasks.loop(minutes=2)
    async def check_updates(self):
        await self.bot.wait_until_ready()

        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT * FROM youtube_alerts") as cursor:
                rows = await cursor.fetchall()

        for guild_id, yt_channel, discord_channel_id, role_id, message, last_video in rows:
            try:
                video = await self.fetch_latest_video(yt_channel)
                if not video:
                    continue

                video_id = video["id"]["videoId"]
                title = video["snippet"]["title"]
                thumb = video["snippet"]["thumbnails"]["high"]["url"]
                url = f"https://youtube.com/watch?v={video_id}"

                if video_id == last_video:
                    continue

                kind = video["snippet"]["liveBroadcastContent"]
                alert_type = "🔴 LIVE NOW" if kind == "live" else "🎬 NEW VIDEO"

                embed = discord.Embed(
                    title=alert_type,
                    description=f"**{title}**\n\n{message}",
                    color=discord.Color.red() if kind == "live" else discord.Color.green()
                )
                embed.set_thumbnail(url=thumb)
                embed.add_field(name="Watch Here", value=url)

                guild = self.bot.get_guild(guild_id)
                if not guild:
                    continue

                channel = guild.get_channel(discord_channel_id)
                role = guild.get_role(role_id)

                if not channel:
                    continue

                await channel.send(content=role.mention if role else None, embed=embed)

                async with aiosqlite.connect(DB_NAME) as db:
                    await db.execute(
                        "UPDATE youtube_alerts SET last_video=? WHERE guild_id=? AND youtube_channel=?",
                        (video_id, guild_id, yt_channel)
                    )
                    await db.commit()

            except Exception as e:
                print("YouTube alert error:", e)

    # =================================================
    # FETCH LATEST VIDEO
    # =================================================
    async def fetch_latest_video(self, channel_id: str):
        url = (
            "https://www.googleapis.com/youtube/v3/search"
            f"?part=snippet&channelId={channel_id}&type=video&order=date&key={YOUTUBE_API_KEY}"
        )

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

        if "items" not in data or len(data["items"]) == 0:
            return None

        return data["items"][0]


# ================= SETUP =================
async def setup(bot: commands.Bot):
    await bot.add_cog(YouTubeAlerts(bot))
