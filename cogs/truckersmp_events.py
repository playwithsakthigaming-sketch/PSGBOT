import discord
import requests
import asyncio
from datetime import datetime, timedelta, timezone
from discord.ext import commands
from discord import app_commands
from bs4 import BeautifulSoup

API_URL = "https://api.truckersmp.com/v2/events/{}"


class TruckersMPEvents(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ================= HELPER =================
    def extract_event_id(self, value: str):
        """Extract event ID from URL or accept raw ID."""
        if "truckersmp.com" in value:
            parts = value.split("/")
            for part in parts:
                if part.isdigit():
                    return part
        return value

    def extract_route_image(self, event_url: str):
        """Extract route image from route section."""
        try:
            page = requests.get(event_url, timeout=10)
            soup = BeautifulSoup(page.text, "html.parser")

            route_section = None
            for header in soup.find_all(["h2", "h3", "h4"]):
                if "route" in header.text.lower():
                    route_section = header.find_next("div")
                    break

            if not route_section:
                return None

            img = route_section.find("img")
            if not img:
                return None

            src = img.get("src")
            if not src:
                return None

            if src.startswith("/"):
                return "https://truckersmp.com" + src

            return src

        except:
            return None

    # ================= REMINDER TASK =================
    async def schedule_reminder(
        self,
        guild: discord.Guild,
        event_name: str,
        event_url: str,
        start_time: datetime,
        reminder_channel: discord.TextChannel,
        reminder_role: discord.Role
    ):
        # Reminder 30 minutes before event
        reminder_time = start_time - timedelta(minutes=30)
        now = datetime.now(timezone.utc)
        delay = (reminder_time - now).total_seconds()

        if delay <= 0:
            return

        await asyncio.sleep(delay)

        # Channel reminder
        if reminder_channel:
            embed = discord.Embed(
                title="⏰ Event Reminder",
                description=f"**{event_name}** starts in 30 minutes!\n{event_url}",
                color=discord.Color.orange()
            )
            await reminder_channel.send(
                content=reminder_role.mention if reminder_role else None,
                embed=embed
            )

        # DM role members
        if reminder_role:
            for member in reminder_role.members:
                try:
                    embed = discord.Embed(
                        title="⏰ Event Reminder",
                        description=f"**{event_name}** starts in 30 minutes!\n{event_url}",
                        color=discord.Color.orange()
                    )
                    await member.send(embed=embed)
                except:
                    pass

    # ================= COMMAND =================
    @app_commands.command(name="event", description="Show TruckersMP event full details")
    async def event(
        self,
        interaction: discord.Interaction,
        event: str,
        slot_number: int = None,
        slot_image: str = None,
        reminder_channel: discord.TextChannel = None,
        reminder_role: discord.Role = None
    ):
        await interaction.response.defer()

        try:
            event_id = self.extract_event_id(event)

            response = requests.get(API_URL.format(event_id), timeout=10)
            data = response.json()

            if not data.get("response"):
                return await interaction.followup.send("❌ Event not found.")

            event_data = data["response"]

            name = event_data["name"]
            server = event_data["server"]["name"]
            start = event_data["start_at"]
            banner = event_data["banner"]
            description = event_data["description"]
            url = event_data["url"]

            # Fix URLs
            if url and url.startswith("/"):
                url = "https://truckersmp.com" + url

            if banner and banner.startswith("/"):
                banner = "https://truckersmp.com" + banner

            # Convert start time
            start_time = datetime.fromisoformat(start.replace("Z", "+00:00"))

            # ================= MAIN EVENT EMBED =================
            embed = discord.Embed(
                title=name,
                description=description,
                color=discord.Color.orange(),
                url=url
            )

            embed.add_field(name="Server", value=server, inline=True)
            embed.add_field(
                name="Start Time",
                value=f"<t:{int(start_time.timestamp())}:F>",
                inline=True
            )

            embed.set_image(url=banner)
            embed.set_footer(text="TruckersMP Event System")

            # ================= SLOT EMBED =================
            slot_embed = None
            if slot_number:
                slot_embed = discord.Embed(
                    title="🚛 Slot Information",
                    color=discord.Color.blue()
                )
                slot_embed.add_field(
                    name="Your Slot",
                    value=f"Slot #{slot_number}",
                    inline=False
                )

                if slot_image:
                    slot_embed.set_image(url=slot_image)

            # ================= ROUTE EMBED =================
            route_embed = None
            route_image = self.extract_route_image(url)

            if route_image:
                route_embed = discord.Embed(
                    title="🗺 Event Route",
                    color=discord.Color.green()
                )
                route_embed.set_image(url=route_image)

            # ================= SEND EMBEDS =================
            await interaction.followup.send(embed=embed)

            if slot_embed:
                await interaction.followup.send(embed=slot_embed)

            if route_embed:
                await interaction.followup.send(embed=route_embed)

            # ================= SCHEDULE REMINDER =================
            if reminder_channel or reminder_role:
                self.bot.loop.create_task(
                    self.schedule_reminder(
                        interaction.guild,
                        name,
                        url,
                        start_time,
                        reminder_channel,
                        reminder_role
                    )
                )

        except Exception as e:
            await interaction.followup.send(f"❌ Error: {str(e)}")


# ================= SETUP =================
async def setup(bot: commands.Bot):
    await bot.add_cog(TruckersMPEvents(bot))
