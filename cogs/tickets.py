import discord, time, io, aiosqlite
from discord.ext import commands
from discord import app_commands

STAFF_ROLE_ID = 1464425870675411064
PREMIUM_ROLE_ID = 1463884209025187880
TRANSCRIPT_CHANNEL_ID = 1463921525307474031
TICKET_COOLDOWN_SECONDS = 1200
DB_NAME = "bot.db"


# ================= DATABASE HELPERS =================
async def save_ticket(channel_id, user_id, category):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT OR REPLACE INTO tickets (channel_id, user_id, claimed_by, category, created_at) VALUES (?,?,?,?,?)",
            (channel_id, user_id, None, category, int(time.time()))
        )
        await db.commit()


async def update_claim(channel_id, staff_id):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "UPDATE tickets SET claimed_by=? WHERE channel_id=?",
            (staff_id, channel_id)
        )
        await db.commit()


async def get_ticket(channel_id):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT user_id, claimed_by FROM tickets WHERE channel_id=?",
            (channel_id,)
        ) as cursor:
            return await cursor.fetchone()


async def delete_ticket(channel_id):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM tickets WHERE channel_id=?", (channel_id,))
        await db.commit()


# ================= COOLDOWN =================
async def check_cooldown(user: discord.Member):
    if user.guild_permissions.administrator:
        return 0
    if any(r.id == STAFF_ROLE_ID for r in user.roles):
        return 0
    if any(r.id == PREMIUM_ROLE_ID for r in user.roles):
        return 0

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT last_created FROM ticket_cooldowns WHERE user_id=?",
            (user.id,)
        ) as cursor:
            row = await cursor.fetchone()

    now = int(time.time())
    if row:
        remaining = TICKET_COOLDOWN_SECONDS - (now - row[0])
        if remaining > 0:
            return remaining
    return 0


async def update_cooldown(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT OR REPLACE INTO ticket_cooldowns (user_id, last_created) VALUES (?,?)",
            (user_id, int(time.time()))
        )
        await db.commit()


# ================= MODAL =================
class TicketModal(discord.ui.Modal):
    def __init__(self, label: str, category: discord.CategoryChannel):
        super().__init__(title=f"🎫 {label} Ticket")
        self.category = category
        self.issue = discord.ui.TextInput(
            label="Describe your issue",
            style=discord.TextStyle.paragraph,
            required=True
        )
        self.add_item(self.issue)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        remaining = await check_cooldown(interaction.user)
        if remaining > 0:
            return await interaction.followup.send(
                f"⏳ Wait **{remaining} seconds** before creating another ticket.\n"
                f"⭐ Premium users have no cooldown.",
                ephemeral=True
            )

        guild = interaction.guild
        staff_role = guild.get_role(STAFF_ROLE_ID)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            staff_role: discord.PermissionOverwrite(read_messages=True, send_messages=False)
        }

        channel = await guild.create_text_channel(
            name=f"ticket-{interaction.user.name}",
            overwrites=overwrites,
            category=self.category,
            topic=str(interaction.user.id)
        )

        await save_ticket(channel.id, interaction.user.id, self.category.name)
        await update_cooldown(interaction.user.id)

        await channel.send(
            f"{interaction.user.mention} {staff_role.mention}\n📌 **Issue:** {self.issue.value}",
            view=TicketControlView(interaction.user.id)
        )

        await interaction.followup.send(f"✅ Ticket created: {channel.mention}", ephemeral=True)


# ================= CONTROL VIEW =================
class TicketControlView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=None)
        self.user_id = user_id

    def is_staff(self, member):
        role = member.guild.get_role(STAFF_ROLE_ID)
        return role in member.roles or member.guild_permissions.administrator

    # -------- CLAIM --------
    @discord.ui.button(label="🖐 Claim", style=discord.ButtonStyle.primary)
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        if not self.is_staff(interaction.user):
            return await interaction.followup.send("❌ Staff only.", ephemeral=True)

        ticket = await get_ticket(interaction.channel.id)
        if ticket and ticket[1]:
            return await interaction.followup.send("❌ Already claimed.", ephemeral=True)

        await update_claim(interaction.channel.id, interaction.user.id)

        await interaction.channel.set_permissions(interaction.user, send_messages=True)
        await interaction.channel.set_permissions(
            interaction.guild.get_member(self.user_id),
            send_messages=False
        )

        await interaction.channel.send(f"🟢 Claimed by {interaction.user.mention}")
        await interaction.followup.send("✅ Ticket claimed.", ephemeral=True)

    # -------- CLOSE --------
    @discord.ui.button(label="🔒 Close", style=discord.ButtonStyle.secondary)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.is_staff(interaction.user):
            return await interaction.response.send_message("❌ Staff only.", ephemeral=True)

        guild = interaction.guild
        await interaction.channel.set_permissions(guild.default_role, read_messages=False)
        await interaction.channel.set_permissions(guild.get_role(STAFF_ROLE_ID), read_messages=False)
        await interaction.channel.set_permissions(
            guild.get_member(self.user_id),
            read_messages=False
        )

        await interaction.channel.send("🔒 Ticket closed.")
        await interaction.response.send_message("Closed & hidden.", ephemeral=True)

    # -------- DELETE (ONLY CLAIMER OR ADMIN) --------
    @discord.ui.button(label="🗑 Delete", style=discord.ButtonStyle.danger)
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket = await get_ticket(interaction.channel.id)
        if not ticket:
            return await interaction.response.send_message("❌ Ticket not found.", ephemeral=True)

        claimed_by = ticket[1]
        if not (interaction.user.guild_permissions.administrator or interaction.user.id == claimed_by):
            return await interaction.response.send_message(
                "❌ Only claimer or admin can delete.",
                ephemeral=True
            )

        await send_transcript(interaction.channel)
        await delete_ticket(interaction.channel.id)
        await interaction.channel.delete()


# ================= TRANSCRIPT =================
async def send_transcript(channel):
    messages = []
    async for msg in channel.history(limit=None, oldest_first=True):
        messages.append(f"[{msg.created_at}] {msg.author}: {msg.content}")

    data = "\n".join(messages)
    file = discord.File(io.BytesIO(data.encode()), filename=f"{channel.name}.txt")

    log_channel = channel.guild.get_channel(TRANSCRIPT_CHANNEL_ID)
    if log_channel:
        await log_channel.send(f"📄 Transcript for {channel.name}", file=file)


# ================= PANEL VIEW =================
class TicketPanelView(discord.ui.View):
    def __init__(self, buttons):
        super().__init__(timeout=None)
        for label, emoji, category in buttons:
            self.add_item(TicketOpenButton(label, emoji, category))


class TicketOpenButton(discord.ui.Button):
    def __init__(self, label, emoji, category):
        super().__init__(label=label, style=discord.ButtonStyle.success, emoji=emoji)
        self.label_name = label
        self.category = category

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(
            TicketModal(self.label_name, self.category)
        )


# ================= COG =================
class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # CREATE PANEL
    @app_commands.command(name="ticket_panel_multi", description="Create ticket panel with categories")
    async def ticket_panel_multi(
        self,
        interaction: discord.Interaction,
        title: str,
        description: str,
        buttons: str,
        role: discord.Role,
        channel: discord.TextChannel,
        imageurl: str = None
    ):
        """
        buttons format:
        Support,🎫,SupportCat|Report,⚠,ReportCat
        """
        await interaction.response.defer(ephemeral=True)

        button_list = []
        for part in buttons.split("|"):
            if part.count(",") != 2:
                return await interaction.followup.send(
                    "❌ Button format error. Use: Name,Emoji,Category",
                    ephemeral=True
                )

            name, emoji, category_name = part.split(",", 2)
            category = discord.utils.get(
                interaction.guild.categories,
                name=category_name.strip()
            )
            if not category:
                return await interaction.followup.send(
                    f"❌ Category `{category_name}` not found.",
                    ephemeral=True
                )

            button_list.append((name.strip(), emoji.strip(), category))

        embed = discord.Embed(title=title, description=description, color=discord.Color.blue())
        if imageurl:
            embed.set_image(url=imageurl)

        await channel.send(role.mention, embed=embed, view=TicketPanelView(button_list))
        await interaction.followup.send("✅ Ticket panel created.", ephemeral=True)

    # ADD USER (SLASH COMMAND)
    @app_commands.command(name="ticket_adduser", description="Add user to this ticket (staff only)")
    async def ticket_adduser(self, interaction: discord.Interaction, user: discord.Member):

        staff_role = interaction.guild.get_role(STAFF_ROLE_ID)
        if not (interaction.user.guild_permissions.administrator or staff_role in interaction.user.roles):
            return await interaction.response.send_message("❌ Staff only.", ephemeral=True)

        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute(
                "SELECT user_id FROM tickets WHERE channel_id=?",
                (interaction.channel.id,)
            ) as cursor:
                ticket = await cursor.fetchone()

        if not ticket:
            return await interaction.response.send_message("❌ This is not a ticket channel.", ephemeral=True)

        await interaction.channel.set_permissions(user, read_messages=True, send_messages=True)
        await interaction.response.send_message(f"✅ {user.mention} added to this ticket.", ephemeral=True)


async def setup(bot):
    bot.add_view(TicketPanelView([]))
    await bot.add_cog(Tickets(bot))
