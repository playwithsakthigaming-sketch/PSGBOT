import discord
from discord.ext import commands, tasks
import time

# ========================
# CONFIG
# ========================
STATUS_CHANNEL_ID = 1415142396341256275  # put your channel ID here
START_TIME = time.time()


class Status(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.status_message_id = None
        self.status_index = 0

        # Status rotation list
        self.status_list = [
            discord.Game(name="Managing servers"),
            discord.Activity(type=discord.ActivityType.watching, name="your community"),
            discord.Activity(type=discord.ActivityType.listening, name="/help commands"),
            discord.Activity(type=discord.ActivityType.competing, name="events"),
        ]

        self.status_loop.start()
        self.presence_loop.start()

    def cog_unload(self):
        self.status_loop.cancel()
        self.presence_loop.cancel()

    # ========================
    # STATUS EMBED BUILDER
    # ========================
    def build_status_embed(self, guild: discord.Guild):
        uptime_seconds = int(time.time() - START_TIME)
        hours = uptime_seconds // 3600
        minutes = (uptime_seconds % 3600) // 60

        member_count = guild.member_count if guild else 0

        bot_status = "Online" if self.bot.is_ready() else "Offline"
        status_icon = "🟢" if bot_status == "Online" else "🔴"

        embed = discord.Embed(
            title=self.bot.user.name,
            description="Bot system information",
            color=discord.Color.green()
        )

        embed.add_field(
            name=f"{status_icon} STATUS",
            value=f"`{bot_status}`",
            inline=False
        )

        embed.add_field(
            name="👥 MEMBERS",
            value=f"`{member_count}`",
            inline=False
        )

        embed.add_field(
            name="📶 LATENCY",
            value=f"`{round(self.bot.latency * 1000)} ms`",
            inline=False
        )

        embed.add_field(
            name="⏱ UPTIME",
            value=f"`{hours} hrs, {minutes} mins`",
            inline=False
        )

        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.set_image(url="https://your-banner-image-link.png")

        return embed

    # ========================
    # AUTO STATUS EMBED LOOP
    # ========================
    @tasks.loop(seconds=60)
    async def status_loop(self):
        await self.bot.wait_until_ready()

        channel = self.bot.get_channel(STATUS_CHANNEL_ID)
        if not channel:
            return

        guild = channel.guild
        embed = self.build_status_embed(guild)

        try:
            if self.status_message_id:
                msg = await channel.fetch_message(self.status_message_id)
                await msg.edit(embed=embed)
            else:
                msg = await channel.send(embed=embed)
                self.status_message_id = msg.id
        except:
            msg = await channel.send(embed=embed)
            self.status_message_id = msg.id

    # ========================
    # PRESENCE ROTATION LOOP
    # ========================
    @tasks.loop(seconds=20)
    async def presence_loop(self):
        await self.bot.wait_until_ready()

        activity = self.status_list[self.status_index]
        await self.bot.change_presence(
            status=discord.Status.online,
            activity=activity
        )

        self.status_index = (self.status_index + 1) % len(self.status_list)


# ========================
# SETUP
# ========================
async def setup(bot: commands.Bot):
    await bot.add_cog(Status(bot))
