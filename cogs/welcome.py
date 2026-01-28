import discord
from discord.ext import commands
from discord import app_commands
import aiosqlite

DB_NAME = "bot.db"

# 🔗 PUT YOUR IMAGE URL HERE
LOGO_URL = "https://files.catbox.moe/c1lm6g.png"  # replace with your image link


class Welcome(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ---------------- SETUP ----------------
    @app_commands.command(name="welcome_setup", description="Setup welcome system (embed only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def welcome_setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        role: discord.Role,
        message: str
    ):
        await interaction.response.defer(ephemeral=True)

        try:
            async with aiosqlite.connect(DB_NAME) as db:
                await db.execute("""
                INSERT OR REPLACE INTO guild_settings
                (guild_id, welcome_channel, welcome_role, welcome_message)
                VALUES (?, ?, ?, ?)
                """, (
                    interaction.guild.id,
                    channel.id,
                    role.id,
                    message
                ))
                await db.commit()

            await interaction.followup.send(
                "✅ Welcome system configured!\n\n"
                "You can use:\n"
                "`{user}` = username\n"
                "`{server}` = server name"
            )

        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}")

    # ---------------- PREVIEW ----------------
    @app_commands.command(name="welcome_preview", description="Preview welcome embed")
    @app_commands.checks.has_permissions(administrator=True)
    async def welcome_preview(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            async with aiosqlite.connect(DB_NAME) as db:
                cursor = await db.execute("""
                SELECT welcome_message FROM guild_settings WHERE guild_id=?
                """, (interaction.guild.id,))
                row = await cursor.fetchone()

            if not row:
                return await interaction.followup.send("❌ Welcome not configured.")

            (message,) = row

            embed = discord.Embed(
                title="🎉 Welcome!",
                description=message.format(
                    user=interaction.user.name,
                    server=interaction.guild.name
                ),
                color=discord.Color.gold()
            )

            embed.set_thumbnail(url=interaction.user.display_avatar.url)
            embed.set_image(url=LOGO_URL)

            await interaction.followup.send(
                content=interaction.user.mention,  # 👈 mention above embed
                embed=embed
            )

        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}")

    # ---------------- MEMBER JOIN ----------------
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        try:
            async with aiosqlite.connect(DB_NAME) as db:
                cursor = await db.execute("""
                SELECT welcome_channel, welcome_role, welcome_message
                FROM guild_settings WHERE guild_id=?
                """, (member.guild.id,))
                row = await cursor.fetchone()

            if not row:
                return

            channel_id, role_id, message = row
            channel = member.guild.get_channel(channel_id)

            # Auto role
            role = member.guild.get_role(role_id)
            if role:
                try:
                    await member.add_roles(role)
                except:
                    pass

            # DM welcome
            try:
                await member.send(
                    message.format(
                        user=member.name,
                        server=member.guild.name
                    )
                )
            except:
                pass

            if not channel:
                return

            embed = discord.Embed(
                title="🎉 Welcome!",
                description=message.format(
                    user=member.name,
                    server=member.guild.name
                ),
                color=discord.Color.gold()
            )

            embed.set_thumbnail(url=member.display_avatar.url)
            embed.set_image(url=LOGO_URL)
            embed.set_footer(text=f"Member #{member.guild.member_count}")

            await channel.send(
                content=member.mention,  # 👈 mention above embed
                embed=embed
            )

        except Exception as e:
            print("Welcome error:", e)


async def setup(bot: commands.Bot):
    await bot.add_cog(Welcome(bot))
