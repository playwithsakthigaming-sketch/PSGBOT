import discord
from discord.ext import commands, tasks
from discord import app_commands
import datetime
import asyncio
import random
import time
import aiosqlite
import os
import sys
import aiohttp

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
        super().__init__(style=discord.ButtonStyle.primary, emoji=emoji, label="")
        self.role = role

    async def callback(self, interaction: discord.Interaction):
        member = interaction.user

        if self.role in member.roles:
            await member.remove_roles(self.role)
            await interaction.response.send_message(
                f"❌ Removed **{self.role.name}**", ephemeral=True
            )
        else:
            await member.add_roles(self.role)
            await interaction.response.send_message(
                f"✅ Added **{self.role.name}**", ephemeral=True
            )


class SelfRoleView(discord.ui.View):
    def __init__(self, role_pairs: list):
        super().__init__(timeout=None)
        for role, emoji in role_pairs:
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
        self.auto_delete_dms.start()

    def cog_unload(self):
        self.auto_delete_dms.cancel()

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
            await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """)
            await db.commit()

    # ========================
    # SETTINGS CHECK
    # ========================
    async def is_dm_autoclean_enabled(self):
        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute(
                "SELECT value FROM settings WHERE key='dm_autoclean'"
            )
            row = await cur.fetchone()
            return row and row[0] == "on"

    # ========================
    # AUTO DELETE DMS
    # ========================
    @tasks.loop(minutes=1)
    async def auto_delete_dms(self):
        await self.bot.wait_until_ready()

        if not await self.is_dm_autoclean_enabled():
            return

        for channel in self.bot.private_channels:
            if isinstance(channel, discord.DMChannel):
                try:
                    async for msg in channel.history(limit=100):
                        if msg.author == self.bot.user:
                            await msg.delete()
                            await asyncio.sleep(1)
                except:
                    pass

    # ========================
    # TOGGLE COMMAND
    # ========================
    @app_commands.command(name="dm_autoclean")
    @app_commands.checks.has_permissions(administrator=True)
    async def dm_autoclean(self, interaction: discord.Interaction, state: str):
        state = state.lower()

        if state not in ["on", "off"]:
            return await interaction.response.send_message("❌ Use `on` or `off`", ephemeral=True)

        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES ('dm_autoclean', ?)",
                (state,)
            )
            await db.commit()

        await interaction.response.send_message(
            f"🧹 DM Auto Cleanup is now **{state.upper()}**",
            ephemeral=True
        )

    # ========================
    # BASIC COMMANDS
    # ========================
    @app_commands.command(name="ping")
    async def ping(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            f"🏓 Pong `{round(self.bot.latency*1000)}ms`", ephemeral=True
        )

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
    # DM COMMANDS
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
    # SELF ROLE
    # ========================
    @app_commands.command(name="selfrole")
    @app_commands.checks.has_permissions(administrator=True)
    async def selfrole(self, interaction: discord.Interaction, channel: discord.TextChannel, title: str, description: str, imageurl: str, roles: str):
        await interaction.response.defer(ephemeral=True)

        pairs = []
        try:
            for item in roles.split(","):
                role_part, emoji = item.split(":")
                role_id = int(role_part.replace("<@&", "").replace(">", ""))
                role = interaction.guild.get_role(role_id)
                if role:
                    pairs.append((role, emoji))
        except:
            return await interaction.followup.send("❌ Format error! Use: @Role:emoji,@Role2:emoji", ephemeral=True)

        embed = discord.Embed(title=title, description=description)
        if imageurl:
            embed.set_image(url=imageurl)

        view = SelfRoleView(pairs)
        await channel.send(embed=embed, view=view)
        await interaction.followup.send("✅ Self role panel created!", ephemeral=True)

    # ========================
    # CLEAR + DELETE + RESTART
    # ========================
    @app_commands.command(name="clear")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clear(self, interaction: discord.Interaction, amount: int):
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"🧹 Deleted {len(deleted)} messages", ephemeral=True)

    @app_commands.command(name="delete_channel")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def delete_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await channel.delete()
        await interaction.response.send_message("🗑 Channel deleted", ephemeral=True)

    @app_commands.command(name="restart")
    @app_commands.checks.has_permissions(administrator=True)
    async def restart(self, interaction: discord.Interaction):
        await interaction.response.send_message("♻ Restarting bot...", ephemeral=True)
        await self.bot.close()
        os.execv(sys.executable, ['python'] + sys.argv)


# ========================
# SETUP
# ========================
async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))
