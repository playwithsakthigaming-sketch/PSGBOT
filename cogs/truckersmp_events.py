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
        """Extract event ID from URL or accept raw ID."""
        if "truckersmp.com" in value:
            parts = value.split("/")
            for part in parts:
                if part.isdigit():
                    return part
        return value

    def extract_route_image(self, event_url: str):
        """Extract route image specifically from the route section."""
        try:
            page = requests.get(event_url, timeout=10)
            soup = BeautifulSoup(page.text, "html.parser")

            # Find the route section
            route_section = None
            for header in soup.find_all(["h2", "h3", "h4"]):
                if "route" in header.text.lower():
                    route_section = header.find_next("div")
                    break

            if not route_section:
                return None

            # Find image inside route section
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

    # ================= COMMAND =================
    @app_commands.command(name="event", description="Show TruckersMP event full details")
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

            # ===== FIX RELATIVE URL =====
            if url and url.startswith("/"):
                url = "https://truckersmp.com" + url

            if banner and banner.startswith("/"):
                banner = "https://truckersmp.com" + banner

            departure = event_data.get("departure", {})
            arrival = event_data.get("arrival", {})

            dep_city = departure.get("city", "Unknown")
            arr_city = arrival.get("city", "Unknown")

            distance = event_data.get("distance", "Unknown")

            # ================= MAIN EVENT EMBED =================
            embed = discord.Embed(
                title=name,
                description=description,
                color=discord.Color.orange(),
                url=url
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
