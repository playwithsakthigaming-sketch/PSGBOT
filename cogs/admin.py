import discord
from discord.ext import commands, tasks
from discord import app_commands
import datetime
import random
import asyncio

# ========================
# CONFIG
# ========================
CHANGELOG_CHANNEL_ID = 123456789012345678  # PUT YOUR CHANGELOG CHANNEL ID HERE


# ========================
# SERVER STATUS VIEW
# ========================
class ServerStatusView(discord.ui.View):
    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=300)
        self.guild = guild

    def get_embed(self):
        online = sum(m.status != discord.Status.offline for m in self.guild.members)

        embed = discord.Embed(
            title="📊 Server Status",
            color=discord.Color.green(),
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name="Server", value=self.guild.name, inline=False)
        embed.add_field(name="Members", value=self.guild.member_count, inline=True)
        embed.add_field(name="Online", value=online, inline=True)
        embed.add_field(name="Channels", value=len(self.guild.channels), inline=True)
        embed.add_field(name="Roles", value=len(self.guild.roles), inline=True)

        if self.guild.icon:
            embed.set_thumbnail(url=self.guild.icon.url)

        return embed

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.green, emoji="🔄")
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="Remove", style=discord.ButtonStyle.red, emoji="🗑")
    async def remove(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.message.delete()


# ========================
# SELF ROLE SYSTEM
# ========================
class SelfRoleButton(discord.ui.Button):
    def __init__(self, role: discord.Role):
        super().__init__(label=role.name, style=discord.ButtonStyle.primary)
        self.role = role

    async def callback(self, interaction: discord.Interaction):
        member = interaction.user
        if self.role in member.roles:
            await member.remove_roles(self.role)
            await interaction.response.send_message(
                f"❌ Removed role **{self.role.name}**", ephemeral=True
            )
        else:
            await member.add_roles(self.role)
            await interaction.response.send_message(
                f"✅ You received role **{self.role.name}**", ephemeral=True
            )


class SelfRoleView(discord.ui.View):
    def __init__(self, roles):
        super().__init__(timeout=None)
        for role in roles:
            self.add_item(SelfRoleButton(role))


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
            await interaction.response.send_message("❌ You already joined!", ephemeral=True)
            return

        self.participants.add(interaction.user.id)
        await interaction.response.send_message("✅ You joined the giveaway!", ephemeral=True)


# ========================
# ADMIN COG
# ========================
class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.status_index = 0
        self.giveaways = {}

        self.status_list = [
            discord.Game(name="Watching moderation"),
            discord.Game(name="Play With Sakthi Gaming"),
        ]

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.status_loop.is_running():
            self.status_loop.start()
            print("✅ Admin Cog Loaded")

    @tasks.loop(seconds=15)
    async def status_loop(self):
        await self.bot.change_presence(activity=self.status_list[self.status_index])
        self.status_index = (self.status_index + 1) % len(self.status_list)

    # ========================
    # CHANGELOG LOGGER (BY ID)
    # ========================
    async def send_changelog(self, embed: discord.Embed):
        channel = self.bot.get_channel(CHANGELOG_CHANNEL_ID)
        if channel:
            await channel.send(embed=embed)

    # ========================
    # /ping
    # ========================
    @app_commands.command(name="ping", description="Check bot latency")
    async def ping(self, interaction: discord.Interaction):
        latency = round(self.bot.latency * 1000)
        await interaction.response.send_message(f"🏓 Pong `{latency}ms`", ephemeral=True)

    # ========================
    # /serverstatus
    # ========================
    @app_commands.command(name="serverstatus", description="Show server status")
    async def serverstatus(self, interaction: discord.Interaction):
        view = ServerStatusView(interaction.guild)
        embed = view.get_embed()
        await interaction.response.send_message(embed=embed, view=view)

    # ========================
    # SELF ROLE (WITH CHANNEL + IMAGE)
    # ========================
    @app_commands.command(name="selfrole", description="🎭 Create self role buttons")
    @app_commands.checks.has_permissions(administrator=True)
    async def selfrole(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        imageurl: str,
        role1: discord.Role,
        role2: discord.Role = None,
        role3: discord.Role = None,
        role4: discord.Role = None,
    ):
        roles = [r for r in [role1, role2, role3, role4] if r]

        embed = discord.Embed(
            title="🎭 Choose Your Role",
            description="Click buttons to get/remove roles",
            color=discord.Color.purple()
        )
        embed.set_image(url=imageurl)

        view = SelfRoleView(roles)
        await channel.send(embed=embed, view=view)

        await interaction.response.send_message(
            f"✅ Self role panel sent to {channel.mention}", ephemeral=True
        )

    # ========================
    # START GIVEAWAY (WITH CHANNEL + IMAGE)
    # ========================
    @app_commands.command(name="giveaway", description="🎁 Start an advanced giveaway")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def giveaway(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        prize: str,
        minutes: int,
        winners: int = 1,
        imageurl: str = None
    ):
        view = GiveawayView()

        embed = discord.Embed(
            title="🎁 Giveaway Started!",
            color=discord.Color.gold(),
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name="Prize", value=prize, inline=False)
        embed.add_field(name="Winners", value=str(winners), inline=False)
        embed.add_field(name="Ends In", value=f"{minutes} minutes", inline=False)
        embed.set_footer(text=f"Hosted by {interaction.user}")

        if imageurl:
            embed.set_image(url=imageurl)

        msg = await channel.send(embed=embed, view=view)

        self.giveaways[msg.id] = {
            "view": view,
            "prize": prize,
            "winners": winners,
            "channel": channel.id
        }

        await interaction.response.send_message(
            f"✅ Giveaway started in {channel.mention}", ephemeral=True
        )

        await asyncio.sleep(minutes * 60)
        await self.finish_giveaway(msg.id)

    # ========================
    # FINISH GIVEAWAY
    # ========================
    async def finish_giveaway(self, message_id: int):
        data = self.giveaways.get(message_id)
        if not data:
            return

        channel = self.bot.get_channel(data["channel"])
        view = data["view"]

        if len(view.participants) == 0:
            await channel.send("❌ Giveaway ended. No participants.")
            return

        winners = random.sample(
            list(view.participants),
            min(data["winners"], len(view.participants))
        )

        winner_mentions = ", ".join(f"<@{w}>" for w in winners)

        embed = discord.Embed(
            title="🎉 Giveaway Ended!",
            color=discord.Color.green()
        )
        embed.add_field(name="Prize", value=data["prize"], inline=False)
        embed.add_field(name="Winners", value=winner_mentions, inline=False)

        await channel.send(embed=embed)
        del self.giveaways[message_id]

    # ========================
    # END GIVEAWAY
    # ========================
    @app_commands.command(name="end_giveaway", description="⏹ End giveaway manually")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def end_giveaway(self, interaction: discord.Interaction, message_id: str):
        await self.finish_giveaway(int(message_id))
        await interaction.response.send_message("✅ Giveaway ended.", ephemeral=True)

    # ========================
    # REROLL GIVEAWAY
    # ========================
    @app_commands.command(name="reroll_giveaway", description="🔁 Reroll giveaway")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def reroll_giveaway(self, interaction: discord.Interaction, message_id: str):
        data = self.giveaways.get(int(message_id))
        if not data:
            await interaction.response.send_message("❌ Giveaway not found.", ephemeral=True)
            return

        view = data["view"]

        if not view.participants:
            await interaction.response.send_message("❌ No participants.", ephemeral=True)
            return

        winner = random.choice(list(view.participants))
        await interaction.response.send_message(f"🎉 New winner: <@{winner}>")

    # ========================
    # DELETE CHANNEL + CHANGELOG
    # ========================
    @app_commands.command(name="delete_channel", description="🗑 Delete channel and log it")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def delete_channel(self, interaction: discord.Interaction, reason: str = "No reason"):
        channel = interaction.channel

        embed = discord.Embed(
            title="📜 Channel Deleted",
            color=discord.Color.red(),
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name="Channel", value=channel.name)
        embed.add_field(name="By", value=interaction.user.mention)
        embed.add_field(name="Reason", value=reason)

        await self.send_changelog(embed)
        await channel.delete(reason=reason)

    # ========================
    # CLEAR CHAT
    # ========================
    @app_commands.command(name="clear_chat", description="🧹 Clear messages")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clear_chat(self, interaction: discord.Interaction, amount: int):
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(
            f"🧹 Deleted {len(deleted)} messages", ephemeral=True
        )


# ========================
# SETUP
# ========================
async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))
