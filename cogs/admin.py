import discord
from discord.ext import commands
from discord import app_commands
import datetime
import asyncio
import random
import time
import aiosqlite
import os
import sys

# ========================
# CONFIG
# ========================
DB_NAME = "bot.db"
CHANGELOG_CHANNEL_ID = 123456789012345678
DM_DELAY = 2
START_TIME = time.time()


# ========================
# CONFIRM VIEW
# ========================
class ConfirmView(discord.ui.View):
    def __init__(self, callback):
        super().__init__(timeout=60)
        self.callback = callback

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await self.callback()
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("❌ Action cancelled.", ephemeral=True)
        self.stop()


# ========================
# SELF ROLE SYSTEM
# ========================
class SelfRoleButton(discord.ui.Button):
    def __init__(self, role: discord.Role, emoji: str):
        super().__init__(style=discord.ButtonStyle.primary, emoji=emoji)
        self.role = role

    async def callback(self, interaction: discord.Interaction):
        member = interaction.user
        if self.role in member.roles:
            await member.remove_roles(self.role)
            await interaction.response.send_message(f"❌ Removed **{self.role.name}**", ephemeral=True)
        else:
            await member.add_roles(self.role)
            await interaction.response.send_message(f"✅ Added **{self.role.name}**", ephemeral=True)


class SelfRoleView(discord.ui.View):
    def __init__(self, pairs):
        super().__init__(timeout=None)
        for role, emoji in pairs:
            self.add_item(SelfRoleButton(role, emoji))


# ========================
# GIVEAWAY VIEW
# ========================
class GiveawayView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.participants = set()

    @discord.ui.button(label="Join Giveaway", style=discord.ButtonStyle.green, emoji="🎉")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id in self.participants:
            return await interaction.response.send_message("❌ Already joined!", ephemeral=True)

        self.participants.add(interaction.user.id)
        await interaction.response.send_message("✅ Joined giveaway!", ephemeral=True)


# ========================
# ADMIN COG
# ========================
class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.loop.create_task(self.setup_db())

    # ========================
    # DATABASE SETUP
    # ========================
    async def setup_db(self):
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("""
            CREATE TABLE IF NOT EXISTS premium (
                user_id INTEGER PRIMARY KEY,
                tier TEXT
            )
            """)
            await db.commit()

    # ========================
    # ERROR HANDLER
    # ========================
    async def cog_app_command_error(self, interaction: discord.Interaction, error):
        if interaction.response.is_done():
            await interaction.followup.send(f"❌ Error: {error}", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ Error: {error}", ephemeral=True)

    # ========================
    # CHANGELOG LOGGER
    # ========================
    async def send_changelog(self, embed: discord.Embed):
        channel = self.bot.get_channel(CHANGELOG_CHANNEL_ID)
        if channel:
            await channel.send(embed=embed)

    # ========================
    # PING
    # ========================
    @app_commands.command(name="ping")
    async def ping(self, interaction: discord.Interaction):
        await interaction.response.send_message(f"🏓 Pong `{round(self.bot.latency*1000)}ms`", ephemeral=True)

    # ========================
    # SERVER INFO
    # ========================
    @app_commands.command(name="serverinfo")
    async def serverinfo(self, interaction: discord.Interaction):
        g = interaction.guild
        online = sum(m.status != discord.Status.offline for m in g.members)

        embed = discord.Embed(title="📊 Server Info", color=discord.Color.green())
        embed.add_field(name="Name", value=g.name)
        embed.add_field(name="Members", value=g.member_count)
        embed.add_field(name="Online", value=online)
        embed.add_field(name="Channels", value=len(g.channels))
        embed.add_field(name="Roles", value=len(g.roles))
        embed.add_field(name="Boost Level", value=g.premium_tier)

        if g.icon:
            embed.set_thumbnail(url=g.icon.url)

        await interaction.response.send_message(embed=embed)

    # ========================
    # BOT INFO
    # ========================
    @app_commands.command(name="botinfo")
    async def botinfo(self, interaction: discord.Interaction):
        uptime = int(time.time() - START_TIME)

        embed = discord.Embed(title="🤖 Bot Info", color=discord.Color.blue())
        embed.add_field(name="Servers", value=len(self.bot.guilds))
        embed.add_field(name="Users", value=len(self.bot.users))
        embed.add_field(name="Latency", value=f"{round(self.bot.latency*1000)}ms")
        embed.add_field(name="Uptime", value=f"{uptime//3600}h {(uptime%3600)//60}m")

        await interaction.response.send_message(embed=embed)

    # ========================
    # PLAYER INFO
    # ========================
    @app_commands.command(name="playerinfo")
    async def playerinfo(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user

        premium_status = "❌ No"
        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute("SELECT tier FROM premium WHERE user_id=?", (member.id,))
            row = await cur.fetchone()
            if row:
                premium_status = f"✅ {row[0]}"

        nitro = "✨ Yes" if member.avatar and member.avatar.is_animated() else "❌ No"
        boost = "💎 Yes" if member.premium_since else "❌ No"

        embed = discord.Embed(title="👤 Player Info", color=discord.Color.blue())
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Username", value=member.name)
        embed.add_field(name="ID", value=member.id)
        embed.add_field(name="Premium(DB)", value=premium_status)
        embed.add_field(name="Nitro", value=nitro)
        embed.add_field(name="Booster", value=boost)
        embed.add_field(name="Joined", value=member.joined_at.strftime("%d-%m-%Y") if member.joined_at else "Unknown")
        embed.add_field(name="Created", value=member.created_at.strftime("%d-%m-%Y"))
        embed.add_field(name="Top Role", value=member.top_role.mention)

        await interaction.response.send_message(embed=embed)

    # ========================
    # SELF ROLE SETUP
    # ========================
    @app_commands.command(name="selfrole")
    @app_commands.checks.has_permissions(administrator=True)
    async def selfrole(self, interaction: discord.Interaction, role1: discord.Role, emoji1: str,
                       role2: discord.Role = None, emoji2: str = None):
        pairs = [(role1, emoji1)]
        if role2 and emoji2:
            pairs.append((role2, emoji2))

        embed = discord.Embed(title="🎭 Self Roles", description="Click buttons to get/remove roles")
        view = SelfRoleView(pairs)
        await interaction.response.send_message(embed=embed, view=view)

    # ========================
    # GIVEAWAY START
    # ========================
    @app_commands.command(name="giveaway")
    @app_commands.checks.has_permissions(administrator=True)
    async def giveaway(self, interaction: discord.Interaction, minutes: int, title: str, imageurl: str = None):
        view = GiveawayView()

        embed = discord.Embed(
            title=f"🎉 Giveaway: {title}",
            description=f"Ends in {minutes} minutes\nClick button to join!",
            color=discord.Color.gold()
        )
        if imageurl:
            embed.set_image(url=imageurl)

        await interaction.channel.send(embed=embed, view=view)
        await interaction.response.send_message("✅ Giveaway started!", ephemeral=True)

        await asyncio.sleep(minutes * 60)

        if not view.participants:
            await interaction.channel.send("❌ No participants joined the giveaway.")
            return

        winner_id = random.choice(list(view.participants))
        winner = interaction.guild.get_member(winner_id)
        await interaction.channel.send(f"🎉 Congratulations {winner.mention}! You won **{title}**")

    # ========================
    # DM USER
    # ========================
    @app_commands.command(name="dm")
    @app_commands.checks.has_permissions(administrator=True)
    async def dm(self, interaction: discord.Interaction, user: discord.User, title: str, message: str):
        embed = discord.Embed(title=title, description=message)

        async def send_dm():
            await user.send(embed=embed)
            await interaction.followup.send("✅ DM Sent", ephemeral=True)

        view = ConfirmView(send_dm)
        await interaction.response.send_message("Confirm DM?", embed=embed, view=view, ephemeral=True)

    # ========================
    # DM ALL ROLE
    # ========================
    @app_commands.command(name="dmall")
    @app_commands.checks.has_permissions(administrator=True)
    async def dmall(self, interaction: discord.Interaction, role: discord.Role, title: str, message: str):
        embed = discord.Embed(title=title, description=message)

        async def send_bulk():
            count = 0
            for m in role.members:
                if not m.bot:
                    try:
                        await m.send(embed=embed)
                        count += 1
                        await asyncio.sleep(DM_DELAY)
                    except:
                        pass
            await interaction.followup.send(f"✅ DM sent to {count} users", ephemeral=True)

        view = ConfirmView(send_bulk)
        await interaction.response.send_message("Confirm DM All?", embed=embed, view=view, ephemeral=True)

    # ========================
    # CLEAR CHAT
    # ========================
    @app_commands.command(name="clear")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clear(self, interaction: discord.Interaction, amount: int):
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"🧹 Deleted {len(deleted)} messages", ephemeral=True)

    # ========================
    # DELETE CHANNEL
    # ========================
    @app_commands.command(name="delete_channel")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def delete_channel(self, interaction: discord.Interaction, reason: str = "No reason"):
        embed = discord.Embed(title="📜 Channel Deleted", color=discord.Color.red())
        embed.add_field(name="Channel", value=interaction.channel.name)
        embed.add_field(name="By", value=interaction.user.mention)
        embed.add_field(name="Reason", value=reason)

        await self.send_changelog(embed)
        await interaction.channel.delete(reason=reason)

    # ========================
    # RESTART BOT
    # ========================
    @app_commands.command(name="restart")
    @app_commands.checks.has_permissions(administrator=True)
    async def restart(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="♻ Restart Bot",
            description="Are you sure you want to restart the bot?",
            color=discord.Color.orange()
        )

        async def do_restart():
            await interaction.followup.send("♻ Bot is restarting...", ephemeral=True)
            await self.bot.close()
            os.execv(sys.executable, ['python'] + sys.argv)

        view = ConfirmView(do_restart)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


# ========================
# SETUP
# ========================
async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))
