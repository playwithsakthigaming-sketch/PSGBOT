import discord
from discord.ext import commands
from discord import app_commands

# =========================================================
# ANNOUNCE COG
# =========================================================

class Announce(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -----------------------------------------------------
    # /announce
    # -----------------------------------------------------
    @app_commands.command(
        name="announce",
        description="📢 Send an announcement (embed or plain text)"
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        channel="Channel to send announcement",
        title="Announcement title",
        message="Announcement text",
        role="Role to mention (optional)",
        use_embed="Send as embed? (true/false)",
        image_url="Image URL (optional, embed only)"
    )
    async def announce(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        title: str,
        message: str,
        role: discord.Role | None = None,
        use_embed: bool = True,
        image_url: str | None = None
    ):
        mention = role.mention if role else ""

        # ---------------- PLAIN TEXT ----------------
        if not use_embed:
            content = f"{mention}\n**{title}**\n{message}" if mention else f"**{title}**\n{message}"
            await channel.send(content)
            return await interaction.response.send_message(
                "✅ Announcement sent (plain text).",
                ephemeral=True
            )

        # ---------------- EMBED ----------------
        embed = discord.Embed(
            title=title,
            description=message,
            color=discord.Color.gold()
        )

        # Get server icon
        guild_icon = interaction.guild.icon.url if interaction.guild.icon else None

        embed.set_footer(
            text="PSGFamily Administration",
            icon_url=guild_icon
        )

        if image_url:
            embed.set_image(url=image_url)

        await channel.send(
            content=mention if mention else None,
            embed=embed
        )

        await interaction.response.send_message(
            "✅ Announcement sent (embed).",
            ephemeral=True
        )

# =========================================================
# SETUP
# =========================================================

async def setup(bot: commands.Bot):
    await bot.add_cog(Announce(bot))
