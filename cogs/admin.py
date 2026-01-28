import discord
from discord.ext import commands
from discord import app_commands
import aiosqlite

DB_NAME = "bot.db"

# ================= DATABASE =================
async def init_custom_cmds():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS custom_commands (
            name TEXT PRIMARY KEY,
            response TEXT
        )
        """)
        await db.commit()

# ================= ADMIN COG =================
class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.loop.create_task(init_custom_cmds())

    # ---------------- CLEAR CHAT ----------------
    @app_commands.command(name="clear", description="🧹 Clear messages")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clear(self, interaction: discord.Interaction, amount: int):
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"✅ Deleted {len(deleted)} messages")

    # ---------------- CREATE CHANNEL ----------------
    @app_commands.command(name="create_channel", description="📁 Create a channel")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def create_channel(self, interaction: discord.Interaction, name: str):
        channel = await interaction.guild.create_text_channel(name)
        await interaction.response.send_message(
            f"✅ Channel created: {channel.mention}", ephemeral=True
        )

    # ---------------- EDIT CHANNEL ----------------
    @app_commands.command(name="edit_channel", description="✏ Edit channel name/topic")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def edit_channel(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        new_name: str = None,
        new_topic: str = None
    ):
        await channel.edit(name=new_name or channel.name, topic=new_topic)
        await interaction.response.send_message(
            f"✅ Channel updated: {channel.mention}", ephemeral=True
        )

    # ---------------- DELETE CHANNEL ----------------
    @app_commands.command(name="delete_channel", description="🗑 Delete a channel")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def delete_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.send_message("✅ Channel deleted", ephemeral=True)
        await channel.delete()

    # ---------------- ADD CUSTOM COMMAND ----------------
    @app_commands.command(name="add_command", description="➕ Add custom command")
    @app_commands.checks.has_permissions(administrator=True)
    async def add_command(self, interaction: discord.Interaction, name: str, response: str):
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "INSERT OR REPLACE INTO custom_commands (name,response) VALUES (?,?)",
                (name.lower(), response)
            )
            await db.commit()

        await interaction.response.send_message(
            f"✅ Custom command `/{name}` added", ephemeral=True
        )

    # ---------------- REMOVE CUSTOM COMMAND ----------------
    @app_commands.command(name="remove_command", description="❌ Remove custom command")
    @app_commands.checks.has_permissions(administrator=True)
    async def remove_command(self, interaction: discord.Interaction, name: str):
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("DELETE FROM custom_commands WHERE name=?", (name.lower(),))
            await db.commit()

        await interaction.response.send_message(
            f"✅ Custom command `{name}` removed", ephemeral=True
        )

    # ---------------- LIST CUSTOM COMMANDS ----------------
    @app_commands.command(name="list_commands", description="📜 List custom commands")
    async def list_commands(self, interaction: discord.Interaction):
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute("SELECT name FROM custom_commands")
            rows = await cursor.fetchall()

        if not rows:
            return await interaction.response.send_message("❌ No custom commands found")

        cmds = ", ".join([f"/{r[0]}" for r in rows])
        await interaction.response.send_message(f"📜 Custom Commands:\n{cmds}")

    # ---------------- ADD EMOJI ----------------
    @app_commands.command(name="add_emoji", description="😄 Add emoji to server")
    @app_commands.checks.has_permissions(manage_emojis=True)
    async def add_emoji(self, interaction: discord.Interaction, name: str, image_url: str):
        try:
            async with self.bot.http_session.get(image_url) as r:
                image = await r.read()
            emoji = await interaction.guild.create_custom_emoji(name=name, image=image)
            await interaction.response.send_message(
                f"✅ Emoji added: {emoji}", ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Failed to add emoji: {e}", ephemeral=True
            )

    # ---------------- CUSTOM COMMAND HANDLER ----------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.content.startswith("/"):
            return

        cmd = message.content[1:].lower()

        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute(
                "SELECT response FROM custom_commands WHERE name=?",
                (cmd,)
            )
            row = await cursor.fetchone()

        if row:
            await message.channel.send(row[0])

# ================= SETUP =================
async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))
