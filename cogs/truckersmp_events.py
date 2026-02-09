import discord
import requests
from discord.ext import commands
from discord import app_commands
from bs4 import BeautifulSoup

API_URL = "https://api.truckersmp.com/v2/events/{}"


class TruckersMPEvents(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ================= HELPER =================
    def extract_event_id(self, value: str):
        if "truckersmp.com" in value:
            parts = value.split("/")
            for part in parts:
                if part.isdigit():
                    return part
        return value

    def extract_route_image(self, event_url: str):
        """Scrape event page and find route image."""
        try:
            page = requests.get(event_url, timeout=10)
            soup = BeautifulSoup(page.text, "html.parser")

            images = soup.find_all("img")

            for img in images:
                src = img.get("src")
                if not src:
                    continue

                # look for route-like images
                if any(word in src.lower() for word in ["route", "map", "convoy"]):
                    if src.startswith("/"):
                        return "https://truckersmp.com" + src
                    return src
        except:
            pass

        return None

    # ================= COMMAND =================
    @app_commands.command(name="event", description="Show TruckersMP event details")
    async def event(
        self,
        interaction: discord.Interaction,
        event: str,
        role: discord.Role = None,
        channel: discord.TextChannel = None,
        slot_number: int = None,
        slot_image: str = None
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
            game = event_data["game"]
            server = event_data["server"]["name"]
            start = event_data["start_at"]
            banner = event_data["banner"]
            description = event_data["description"]
            url = event_data["url"]

            # ================= MAIN EVENT EMBED =================
            embed = discord.Embed(
                title=name,
                description=description[:300] + "...",
                color=discord.Color.orange(),
                url=url
            )

            embed.add_field(name="🎮 Game", value=game, inline=True)
            embed.add_field(name="🖥 Server", value=server, inline=True)
            embed.add_field(name="🕒 Start Time", value=start, inline=False)

            if channel:
                embed.add_field(name="📍 Meeting Channel", value=channel.mention)

            if role:
                embed.add_field(name="👥 Event Role", value=role.mention)

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

            # ================= SEND =================
            await interaction.followup.send(embed=embed)

            if slot_embed:
                await interaction.followup.send(embed=slot_embed)

            if route_embed:
                await interaction.followup.send(embed=route_embed)

        except Exception as e:
            await interaction.followup.send(f"❌ Error: {str(e)}")


# ================= SETUP =================
async def setup(bot: commands.Bot):
    await bot.add_cog(TruckersMPEvents(bot))
