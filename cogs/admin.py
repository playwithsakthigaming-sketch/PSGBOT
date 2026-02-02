import discord
from discord.ext import commands
from discord import app_commands
import datetime
import random
import asyncio
import time

# ========================
# CONFIG
# ========================
CHANGELOG_CHANNEL_ID = 123456789012345678  # PUT YOUR CHANGELOG CHANNEL ID HERE
DM_DELAY = 2  # seconds between each DM
START_TIME = time.time()


# ========================
# CONFIRMATION VIEW
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
        await interaction.response.send_message("❌ DM cancelled.", ephemeral=True)
        self.stop()


# ========================
# SELF ROLE SYSTEM (EMOJI ONLY)
# ========================
class SelfRoleButton(discord.ui.Button):
    def __init__(self, role: discord.Role, emoji: str):
        super().__init__(label="", style=discord.ButtonStyle.primary, emoji=emoji)
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
        self.giveaways = {}

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
    @app_commands.command(name="ping", description="🏓 Check bot latency")
    async def ping(self, interaction: discord.Interaction):
        latency = round(self.bot.latency * 1000)
        await interaction.response.send_message(f"🏓 Pong! `{latency}ms`", ephemeral=True)

    # ========================
    # SERVER STATUS
    # ========================
    @app_commands.command(name="serverstatus", description="📊 Show server status")
    async def serverstatus(self, interaction: discord.Interaction):
        guild = interaction.guild
        online = sum(m.status != discord.Status.offline for m in guild.members)

        embed = discord.Embed(
            title="📊 Server Status",
            color=discord.Color.green(),
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name="Server", value=guild.name, inline=False)
        embed.add_field(name="Members", value=guild.member_count, inline=True)
        embed.add_field(name="Online", value=online, inline=True)
        embed.add_field(name="Channels", value=len(guild.channels), inline=True)
        embed.add_field(name="Roles", value=len(guild.roles), inline=True)
        embed.add_field(name="Boost Level", value=guild.premium_tier, inline=True)

        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        await interaction.response.send_message(embed=embed)

    # ========================
    # BOT INFO
    # ========================
    @app_commands.command(name="botinfo", description="🤖 Show bot information")
    async def botinfo(self, interaction: discord.Interaction):
        uptime = int(time.time() - START_TIME)

        embed = discord.Embed(
            title="🤖 Bot Information",
            color=discord.Color.blue(),
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name="Servers", value=len(self.bot.guilds), inline=True)
        embed.add_field(name="Users", value=len(self.bot.users), inline=True)
        embed.add_field(name="Latency", value=f"{round(self.bot.latency*1000)}ms", inline=True)
        embed.add_field(name="Uptime", value=f"{uptime//3600}h {(uptime%3600)//60}m", inline=True)
        embed.add_field(name="Python", value="discord.py", inline=True)

        await interaction.response.send_message(embed=embed)

    # ========================
    # PLAYER STATUS
    # ========================
    @app_commands.command(name="playerstatus", description="👥 Show member status counts")
    async def playerstatus(self, interaction: discord.Interaction):
        guild = interaction.guild

        online = len([m for m in guild.members if m.status == discord.Status.online])
        idle = len([m for m in guild.members if m.status == discord.Status.idle])
        dnd = len([m for m in guild.members if m.status == discord.Status.dnd])
        offline = len([m for m in guild.members if m.status == discord.Status.offline])

        embed = discord.Embed(
            title="👥 Player Status",
            color=discord.Color.purple(),
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name="🟢 Online", value=online, inline=True)
        embed.add_field(name="🌙 Idle", value=idle, inline=True)
        embed.add_field(name="⛔ DND", value=dnd, inline=True)
        embed.add_field(name="⚫ Offline", value=offline, inline=True)

        await interaction.response.send_message(embed=embed)

    # ========================
    # DM USER (ADVANCED)
    # ========================
    @app_commands.command(name="dm", description="📩 Send embed DM to a user")
    @app_commands.checks.has_permissions(administrator=True)
    async def dm(self, interaction: discord.Interaction, user: discord.User, title: str, message: str, imageurl: str = None):
        embed = discord.Embed(title=title, description=message, color=discord.Color.blue())
        if imageurl:
            embed.set_image(url=imageurl)

        async def send_dm():
            try:
                await user.send(embed=embed)
                await interaction.followup.send(f"✅ DM sent to {user.mention}", ephemeral=True)
            except:
                await interaction.followup.send("❌ Could not DM this user.", ephemeral=True)

        view = ConfirmView(send_dm)
        await interaction.response.send_message("⚠️ Confirm sending DM?", embed=embed, view=view, ephemeral=True)

    # ========================
    # DM ALL ROLE MEMBERS
    # ========================
    @app_commands.command(name="dmall", description="📢 DM all members of a role")
    @app_commands.checks.has_permissions(administrator=True)
    async def dmall(self, interaction: discord.Interaction, role: discord.Role, title: str, message: str, imageurl: str = None):
        embed = discord.Embed(title=title, description=message, color=discord.Color.orange())
        if imageurl:
            embed.set_image(url=imageurl)

        async def send_bulk_dm():
            count = 0
            for member in role.members:
                if member.bot:
                    continue
                try:
                    await member.send(embed=embed)
                    count += 1
                    await asyncio.sleep(DM_DELAY)
                except:
                    pass

            await interaction.followup.send(f"✅ DM sent to {count} members of {role.name}", ephemeral=True)

        view = ConfirmView(send_bulk_dm)
        await interaction.response.send_message("⚠️ Confirm sending DM to all role members?", embed=embed, view=view, ephemeral=True)

    # ========================
    # CLEAR CHAT
    # ========================
    @app_commands.command(name="clear_chat", description="🧹 Clear messages")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clear_chat(self, interaction: discord.Interaction, amount: int):
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"🧹 Deleted {len(deleted)} messages", ephemeral=True)

    # ========================
    # DELETE CHANNEL + CHANGELOG
    # ========================
    @app_commands.command(name="delete_channel", description="🗑 Delete channel and log it")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def delete_channel(self, interaction: discord.Interaction, reason: str = "No reason"):
        embed = discord.Embed(title="📜 Channel Deleted", color=discord.Color.red())
        embed.add_field(name="Channel", value=interaction.channel.name)
        embed.add_field(name="By", value=interaction.user.mention)
        embed.add_field(name="Reason", value=reason)

        await self.send_changelog(embed)
        await interaction.channel.delete(reason=reason)


# ========================
# SETUP
# ========================
async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))
