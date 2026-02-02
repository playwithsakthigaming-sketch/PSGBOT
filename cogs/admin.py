import discord
from discord.ext import commands
from discord import app_commands
import datetime
import random
import asyncio

# ========================
# CONFIG
# ========================
CHANGELOG_CHANNEL_ID = 123456789012345678  # PUT YOUR CHANGELOG CHANNEL ID HERE
DM_DELAY = 2  # seconds between each DM to avoid rate limit


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
    # DM USER (ADVANCED)
    # ========================
    @app_commands.command(name="dm", description="📩 Send embed DM to a user")
    @app_commands.checks.has_permissions(administrator=True)
    async def dm(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        title: str,
        message: str,
        imageurl: str = None
    ):
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
        await interaction.response.send_message(
            f"⚠️ Confirm sending DM to {user.mention}?",
            embed=embed,
            view=view,
            ephemeral=True
        )

    # ========================
    # DM ALL ROLE MEMBERS
    # ========================
    @app_commands.command(name="dmall", description="📢 DM all members of a role")
    @app_commands.checks.has_permissions(administrator=True)
    async def dmall(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        title: str,
        message: str,
        imageurl: str = None
    ):
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

            await interaction.followup.send(
                f"✅ DM sent to {count} members of {role.name}",
                ephemeral=True
            )

        view = ConfirmView(send_bulk_dm)
        await interaction.response.send_message(
            f"⚠️ Confirm sending DM to all members of **{role.name}**?",
            embed=embed,
            view=view,
            ephemeral=True
        )

    # ========================
    # SELF ROLE
    # ========================
    @app_commands.command(name="selfrole", description="🎭 Create emoji selfrole panel")
    @app_commands.checks.has_permissions(administrator=True)
    async def selfrole(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        title: str,
        imageurl: str,
        role1: discord.Role,
        emoji1: str,
        role2: discord.Role = None,
        emoji2: str = None,
        role3: discord.Role = None,
        emoji3: str = None,
        role4: discord.Role = None,
        emoji4: str = None,
    ):
        pairs = []
        if role1: pairs.append((role1, emoji1))
        if role2: pairs.append((role2, emoji2))
        if role3: pairs.append((role3, emoji3))
        if role4: pairs.append((role4, emoji4))

        embed = discord.Embed(
            title=title,
            description="Click emoji to get/remove role",
            color=discord.Color.purple()
        )
        embed.set_image(url=imageurl)

        await channel.send(embed=embed, view=SelfRoleView(pairs))
        await interaction.response.send_message(
            f"✅ Selfrole panel sent to {channel.mention}", ephemeral=True
        )

    # ========================
    # POLL
    # ========================
    @app_commands.command(name="poll", description="📊 Create a poll")
    async def poll(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        title: str,
        question: str,
        imageurl: str = None,
        option1: str = None,
        option2: str = None,
        option3: str = None,
        option4: str = None,
    ):
        embed = discord.Embed(title=title, description=question, color=discord.Color.blue())
        if imageurl:
            embed.set_image(url=imageurl)

        options = [option1, option2, option3, option4]
        emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣"]

        text = ""
        for i, opt in enumerate(options):
            if opt:
                text += f"{emojis[i]} {opt}\n"

        embed.add_field(name="Options", value=text, inline=False)
        msg = await channel.send(embed=embed)

        for i, opt in enumerate(options):
            if opt:
                await msg.add_reaction(emojis[i])

        await interaction.response.send_message(
            f"✅ Poll sent to {channel.mention}", ephemeral=True
        )

    # ========================
    # GIVEAWAY
    # ========================
    @app_commands.command(name="giveaway", description="🎁 Start giveaway")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def giveaway(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        title: str,
        prize: str,
        minutes: int,
        winners: int = 1,
        imageurl: str = None
    ):
        view = GiveawayView()

        embed = discord.Embed(title=title, color=discord.Color.gold())
        embed.add_field(name="Prize", value=prize)
        embed.add_field(name="Winners", value=str(winners))
        embed.add_field(name="Ends In", value=f"{minutes} minutes")
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

    async def finish_giveaway(self, message_id: int):
        data = self.giveaways.get(message_id)
        if not data:
            return

        channel = self.bot.get_channel(data["channel"])
        view = data["view"]

        if not view.participants:
            return await channel.send("❌ No participants.")

        winners = random.sample(
            list(view.participants),
            min(data["winners"], len(view.participants))
        )
        mentions = ", ".join(f"<@{w}>" for w in winners)

        embed = discord.Embed(title="🎉 Giveaway Ended!", color=discord.Color.green())
        embed.add_field(name="Prize", value=data["prize"])
        embed.add_field(name="Winners", value=mentions)

        await channel.send(embed=embed)
        del self.giveaways[message_id]

    @app_commands.command(name="end_giveaway")
    async def end_giveaway(self, interaction: discord.Interaction, message_id: str):
        await self.finish_giveaway(int(message_id))
        await interaction.response.send_message("✅ Giveaway ended.", ephemeral=True)

    @app_commands.command(name="reroll_giveaway")
    async def reroll_giveaway(self, interaction: discord.Interaction, message_id: str):
        data = self.giveaways.get(int(message_id))
        if not data:
            return await interaction.response.send_message("❌ Giveaway not found.", ephemeral=True)

        winner = random.choice(list(data["view"].participants))
        await interaction.response.send_message(f"🎉 New winner: <@{winner}>")

    # ========================
    # DELETE CHANNEL + CHANGELOG
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
    # CLEAR CHAT
    # ========================
    @app_commands.command(name="clear_chat")
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
