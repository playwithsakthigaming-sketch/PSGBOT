import discord
from discord.ext import commands
from discord import app_commands
import aiosqlite
import aiohttp

DB_NAME = "links.db"
UPLOAD_API = "https://files.psgfamily.online/upload"


class LinkStorage(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        bot.loop.create_task(self.init_db())

    # ===============================
    # DATABASE
    # ===============================
    async def init_db(self):
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS links (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER,
                    name TEXT,
                    url TEXT
                )
            """)
            await db.commit()

    # ===============================
    # FILE UPLOAD
    # ===============================
    async def upload_to_server(self, file: discord.Attachment):
        try:
            async with aiohttp.ClientSession() as session:
                data = aiohttp.FormData()
                file_bytes = await file.read()
                data.add_field("file", file_bytes, filename=file.filename)

                async with session.post(UPLOAD_API, data=data) as resp:
                    if resp.status != 200:
                        return None
                    result = await resp.json()
                    return result.get("url")
        except:
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
        # Prevent Discord timeout
        await interaction.response.defer(ephemeral=True)

        if not url and not file:
            return await interaction.followup.send(
                "❌ Provide a URL or upload a file."
            )

        # Upload file if provided
        if file:
            uploaded_url = await self.upload_to_server(file)
            if not uploaded_url:
                return await interaction.followup.send(
                    "❌ File upload failed."
                )
            url = uploaded_url

        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "INSERT INTO links (guild_id, name, url) VALUES (?, ?, ?)",
                (interaction.guild_id, name, url)
            )
            await db.commit()

        await interaction.followup.send(
            f"✅ **{name}** saved:\n{url}"
        )

    # ===============================
    # LIST LINKS
    # ===============================
    @app_commands.command(name="links", description="Show stored links")
    async def links(self, interaction: discord.Interaction):
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute(
                "SELECT id, name, url FROM links WHERE guild_id=?",
                (interaction.guild_id,)
            )
            rows = await cursor.fetchall()

        if not rows:
            return await interaction.response.send_message(
                "No links stored.",
                ephemeral=True
            )

        embed = discord.Embed(
            title="Stored Links",
            color=discord.Color.blue()
        )

        for link_id, name, url in rows:
            embed.add_field(
                name=f"{link_id}. {name}",
                value=url,
                inline=False
            )

        await interaction.response.send_message(embed=embed)

    # ===============================
    # REMOVE LINK
    # ===============================
    @app_commands.command(name="removelink", description="Remove a stored link")
    @app_commands.describe(link_id="ID of the link to remove")
    async def removelink(self, interaction: discord.Interaction, link_id: int):
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "DELETE FROM links WHERE id=? AND guild_id=?",
                (link_id, interaction.guild_id)
            )
            await db.commit()

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
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "DELETE FROM links WHERE guild_id=?",
                (interaction.guild_id,)
            )
            await db.commit()

        await interaction.response.send_message(
            "🗑️ All links cleared.",
            ephemeral=True
        )


# ===============================
# REQUIRED SETUP FUNCTION
# ===============================
async def setup(bot):
    await bot.add_cog(LinkStorage(bot))
