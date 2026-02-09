import discord
import aiosqlite
import re
import requests
from bs4 import BeautifulSoup
from discord.ext import commands
from discord import app_commands

DB_NAME = "bot.db"

IMAGE_REGEX = r'!\[\]\((https?:\/\/[^\s]+)\)'


# ================= IMAGE PARSER =================
def extract_images(text: str):
    return re.findall(IMAGE_REGEX, text)


def remove_image_tags(text: str):
    return re.sub(IMAGE_REGEX, "", text)


# ================= TRUCKERSMP ROUTE FETCH =================
def fetch_route_image(event_url: str):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(event_url, headers=headers, timeout=15)
        soup = BeautifulSoup(res.text, "html.parser")

        img = soup.find("img", {"class": "img-fluid"})
        if img and img.get("src"):
            return img["src"]

    except Exception as e:
        print("Route fetch error:", e)

    return None


# ================= EMBED BUILDERS =================
def build_main_embed(title, description, main_image=None):
    embed = discord.Embed(
        title=title,
        description=description,
        color=discord.Color.orange()
    )
    if main_image:
        embed.set_image(url=main_image)
    return embed


def build_slot_embed(slot_image):
    embed = discord.Embed(
        title="🚚 Slot Information",
        color=discord.Color.blue()
    )
    embed.set_image(url=slot_image)
    return embed


def build_route_embed(route_image):
    embed = discord.Embed(
        title="🗺 Route Map",
        color=discord.Color.green()
    )
    embed.set_image(url=route_image)
    return embed


# ================= COG =================
class TruckersMPEvents(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def init_db(self):
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("""
            CREATE TABLE IF NOT EXISTS truck_events (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER,
                role_id INTEGER,
                title TEXT,
                description TEXT,
                event_url TEXT
            )
            """)
            await db.commit()

    # ================= /event COMMAND =================
    @app_commands.command(name="event", description="Send TruckersMP event embed")
    @app_commands.checks.has_permissions(administrator=True)
    async def event(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        role: discord.Role,
        title: str,
        description: str,
        event_url: str = None
    ):
        await interaction.response.defer(ephemeral=True)

        # Save event
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("""
            INSERT OR REPLACE INTO truck_events
            (guild_id, channel_id, role_id, title, description, event_url)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (
                interaction.guild.id,
                channel.id,
                role.id,
                title,
                description,
                event_url
            ))
            await db.commit()

        # Extract images
        images = extract_images(description)
        clean_desc = remove_image_tags(description)

        main_image = images[0] if images else None
        slot_image = images[1] if len(images) > 1 else None

        # Fetch route image
        route_image = None
        if event_url:
            route_image = fetch_route_image(event_url)

        try:
            # MAIN EMBED
            main_embed = build_main_embed(title, clean_desc, main_image)

            await channel.send(
                content=role.mention if role else None,
                embed=main_embed
            )

            # SLOT EMBED
            if slot_image:
                await channel.send(embed=build_slot_embed(slot_image))

            # ROUTE EMBED
            if route_image:
                await channel.send(embed=build_route_embed(route_image))

        except Exception as e:
            print("Event send error:", e)

        await interaction.followup.send("✅ Event sent successfully.")


# ================= SETUP =================
async def setup(bot: commands.Bot):
    cog = TruckersMPEvents(bot)
    await cog.init_db()
    await bot.add_cog(cog)
