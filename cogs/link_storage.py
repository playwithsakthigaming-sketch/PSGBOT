import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import os
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
UPLOAD_API = "https://files.psgfamily.online/upload"

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}


class LinkStorage(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ===============================
    # FILE UPLOAD
    # ===============================
    async def upload_to_server(self, file: discord.Attachment, name: str):
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            ) as session:
                data = aiohttp.FormData()
                file_bytes = await file.read()

                data.add_field("file", file_bytes, filename=file.filename)
                data.add_field("name", name)

                async with session.post(UPLOAD_API, data=data) as resp:
                    text = await resp.text()
                    print("Upload status:", resp.status)
                    print("Upload response:", text)

                    if resp.status != 200:
                        return None

                    result = await resp.json()
                    return result.get("url")

        except Exception as e:
            print("Upload error:", e)
            return None

    # ===============================
    # ADD LINK
    # ===============================
    @app_commands.command(name="addlink", description="Store a link or upload a file")
    @app_commands.describe(
        name="Name for the link",
        url="Optional URL",
        file="Optional file attachment"
    )
    async def addlink(
        self,
        interaction: discord.Interaction,
        name: str,
        url: str = None,
        file: discord.Attachment = None
    ):
        await interaction.response.defer(ephemeral=True)

        if not url and not file:
            return await interaction.followup.send(
                "❌ Provide a URL or upload a file."
            )

        # Upload file if provided
        if file:
            uploaded_url = await self.upload_to_server(file, name)
            if not uploaded_url:
                return await interaction.followup.send(
                    "❌ File upload failed."
                )
            url = uploaded_url

        payload = {
            "guild_id": interaction.guild_id,
            "name": name,
            "url": url
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{SUPABASE_URL}/rest/v1/links",
                headers=HEADERS,
                json=payload
            ) as resp:
                if resp.status not in (200, 201):
                    return await interaction.followup.send(
                        "❌ Failed to save link."
                    )

        await interaction.followup.send(
            f"✅ **{name}** saved:\n{url}"
        )

    # ===============================
    # LIST LINKS
    # ===============================
    @app_commands.command(name="links", description="Show stored links")
    async def links(self, interaction: discord.Interaction):
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{SUPABASE_URL}/rest/v1/links?guild_id=eq.{interaction.guild_id}",
                headers=HEADERS
            ) as resp:
                if resp.status != 200:
                    return await interaction.response.send_message(
                        "❌ Failed to fetch links.",
                        ephemeral=True
                    )
                rows = await resp.json()

        if not rows:
            return await interaction.response.send_message(
                "No links stored.",
                ephemeral=True
            )

        embed = discord.Embed(
            title="Stored Links",
            color=discord.Color.blue()
        )

        for row in rows:
            embed.add_field(
                name=f"{row['id']}. {row['name']}",
                value=row["url"],
                inline=False
            )

        await interaction.response.send_message(embed=embed)

    # ===============================
    # REMOVE LINK
    # ===============================
    @app_commands.command(name="removelink", description="Remove a stored link")
    @app_commands.describe(link_id="ID of the link to remove")
    async def removelink(self, interaction: discord.Interaction, link_id: int):
        async with aiohttp.ClientSession() as session:
            async with session.delete(
                f"{SUPABASE_URL}/rest/v1/links?id=eq.{link_id}&guild_id=eq.{interaction.guild_id}",
                headers=HEADERS
            ) as resp:
                if resp.status not in (200, 204):
                    return await interaction.response.send_message(
                        "❌ Failed to remove link.",
                        ephemeral=True
                    )

        await interaction.response.send_message(
            "🗑️ Link removed.",
            ephemeral=True
        )

    # ===============================
    # CLEAR ALL LINKS
    # ===============================
    @app_commands.command(name="clearlinks", description="Remove all stored links")
    @app_commands.checks.has_permissions(administrator=True)
    async def clearlinks(self, interaction: discord.Interaction):
        async with aiohttp.ClientSession() as session:
            async with session.delete(
                f"{SUPABASE_URL}/rest/v1/links?guild_id=eq.{interaction.guild_id}",
                headers=HEADERS
            ) as resp:
                if resp.status not in (200, 204):
                    return await interaction.response.send_message(
                        "❌ Failed to clear links.",
                        ephemeral=True
                    )

        await interaction.response.send_message(
            "🗑️ All links cleared.",
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(LinkStorage(bot))
