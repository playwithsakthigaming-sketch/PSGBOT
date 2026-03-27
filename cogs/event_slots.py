import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiosqlite
import aiohttp
from datetime import datetime

DB_NAME = "slots.db"
STAFF_CHANNEL_ID = 1465720466420269121
STAFF_ROLE_ID = 1419223859483115591  # 🔁 CHANGE


# ===============================
# DATABASE
# ===============================
async def setup_database():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            event_id INTEGER,
            event_name TEXT,
            event_time INTEGER
        );

        CREATE TABLE IF NOT EXISTS panels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER,
            panel_name TEXT,
            slot_image TEXT,
            message_id INTEGER,
            channel_id INTEGER
        );

        CREATE TABLE IF NOT EXISTS slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            panel_id INTEGER,
            slot_number INTEGER,
            booked_by INTEGER,
            vtc_name TEXT,
            vtc_url TEXT,
            position TEXT,
            member_count INTEGER,
            status TEXT DEFAULT 'open'
        );

        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            panel_id INTEGER,
            slot_number INTEGER,
            user_id INTEGER,
            vtc_name TEXT,
            action TEXT,
            timestamp INTEGER
        );
        """)
        await db.commit()


# ===============================
# MODAL
# ===============================
class BookingModal(discord.ui.Modal, title="Slot Booking"):
    def __init__(self, cog, panel_id, slot_number):
        super().__init__()
        self.cog = cog
        self.panel_id = panel_id
        self.slot_number = slot_number

        self.vtc_name = discord.ui.TextInput(label="VTC Name", required=True)
        self.vtc_url = discord.ui.TextInput(label="VTC URL", required=True)
        self.position = discord.ui.TextInput(label="Position", required=True)
        self.member_count = discord.ui.TextInput(label="Member Count", required=True)

        self.add_item(self.vtc_name)
        self.add_item(self.vtc_url)
        self.add_item(self.position)
        self.add_item(self.member_count)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            count = int(self.member_count.value)
        except:
            return await interaction.response.send_message("❌ Invalid number", ephemeral=True)

        await self.cog.process_booking(
            interaction, self.panel_id, self.slot_number,
            self.vtc_name.value, self.vtc_url.value,
            self.position.value, count
        )


# ===============================
# DROPDOWN
# ===============================
class SlotSelect(discord.ui.Select):
    def __init__(self, panel_id, slots):
        options = [
            discord.SelectOption(label=f"Slot {s}", value=str(s))
            for s, status, _ in slots if status == "open"
        ]

        if not options:
            options = [discord.SelectOption(label="No slots available", value="none")]

        super().__init__(placeholder="Select a slot...", options=options)
        self.panel_id = panel_id

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            return await interaction.response.send_message("❌ No slots", ephemeral=True)

        cog = interaction.client.get_cog("SlotBooking")
        await interaction.response.send_modal(
            BookingModal(cog, self.panel_id, int(self.values[0]))
        )


class SlotView(discord.ui.View):
    def __init__(self, panel_id, slots):
        super().__init__(timeout=None)
        self.add_item(SlotSelect(panel_id, slots))


# ===============================
# STAFF VIEW
# ===============================
class StaffApproveView(discord.ui.View):
    def __init__(self, panel_id, slot_number):
        super().__init__(timeout=None)
        self.panel_id = panel_id
        self.slot_number = slot_number

    def is_staff(self, interaction):
        return any(role.id == STAFF_ROLE_ID for role in interaction.user.roles)

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, _):

        if not self.is_staff(interaction):
            return await interaction.response.send_message("❌ No permission", ephemeral=True)

        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute("SELECT booked_by FROM slots WHERE panel_id=? AND slot_number=?",
                                      (self.panel_id, self.slot_number))
            user_id = (await cursor.fetchone())[0]

            cursor = await db.execute("SELECT event_id, slot_image FROM panels WHERE id=?", (self.panel_id,))
            event_id, slot_image = await cursor.fetchone()

            cursor = await db.execute("SELECT event_name FROM events WHERE event_id=?", (event_id,))
            event_name = (await cursor.fetchone())[0]

            await db.execute("UPDATE slots SET status='booked' WHERE panel_id=? AND slot_number=?",
                             (self.panel_id, self.slot_number))

            await db.execute("INSERT INTO history VALUES (NULL,?,?,?,?, 'approved', strftime('%s','now'))",
                             (self.panel_id, self.slot_number, user_id, ""))

            await db.commit()

        # DM
        user = interaction.client.get_user(user_id)
        if user:
            embed = discord.Embed(title="✅ Slot Approved", color=discord.Color.green())
            embed.add_field(name="Event", value=event_name, inline=False)
            embed.add_field(name="Slot", value=f"Slot {self.slot_number}", inline=False)
            if slot_image:
                embed.set_image(url=slot_image)
            await user.send(embed=embed)

        await interaction.message.delete()
        await interaction.response.send_message("✅ Approved", ephemeral=True)
        await interaction.client.get_cog("SlotBooking").refresh_panel(self.panel_id)

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, _):

        if not self.is_staff(interaction):
            return await interaction.response.send_message("❌ No permission", ephemeral=True)

        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute("SELECT booked_by FROM slots WHERE panel_id=? AND slot_number=?",
                                      (self.panel_id, self.slot_number))
            user_id = (await cursor.fetchone())[0]

            cursor = await db.execute("SELECT event_id FROM panels WHERE id=?", (self.panel_id,))
            event_id = (await cursor.fetchone())[0]

            cursor = await db.execute("SELECT event_name FROM events WHERE event_id=?", (event_id,))
            event_name = (await cursor.fetchone())[0]

            await db.execute("UPDATE slots SET status='open', booked_by=NULL WHERE panel_id=? AND slot_number=?",
                             (self.panel_id, self.slot_number))

            await db.commit()

        user = interaction.client.get_user(user_id)
        if user:
            embed = discord.Embed(title="❌ Slot Rejected", color=discord.Color.red())
            embed.add_field(name="Event", value=event_name, inline=False)
            embed.add_field(name="Message", value="Your slot has been rejected.\nContact event manager.")
            await user.send(embed=embed)

        await interaction.message.delete()
        await interaction.response.send_message("❌ Rejected", ephemeral=True)
        await interaction.client.get_cog("SlotBooking").refresh_panel(self.panel_id)


# ===============================
# MAIN COG
# ===============================
class SlotBooking(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        bot.loop.create_task(setup_database())
        self.auto_refresh.start()

    def cog_unload(self):
        self.auto_refresh.cancel()

    async def cog_app_command_error(self, interaction, error):
        if isinstance(error, app_commands.errors.MissingRole):
            await interaction.response.send_message("❌ You don’t have permission", ephemeral=True)

    def build_slot_text(self, slots):
        return "\n".join([
            f"🅿️ Slot {s}: Available" if status == "open"
            else f"🟡 Slot {s}: Pending"
            else f"🔴 Slot {s}: {vtc}"
            for s, status, vtc in slots
        ])

    @tasks.loop(seconds=10)
    async def auto_refresh(self):
        async with aiosqlite.connect(DB_NAME) as db:
            panels = await db.execute_fetchall("SELECT id FROM panels WHERE message_id IS NOT NULL")

        for (pid,) in panels:
            await self.refresh_panel(pid)

    # COMMANDS
    @app_commands.command(name="leaderboard")
    async def leaderboard(self, interaction: discord.Interaction, event_id: int):
        async with aiosqlite.connect(DB_NAME) as db:
            rows = await db.execute_fetchall("""
            SELECT vtc_name, COUNT(*) FROM history h
            JOIN panels p ON h.panel_id=p.id
            WHERE p.event_id=? GROUP BY vtc_name
            """, (event_id,))

        embed = discord.Embed(title=f"🏆 Event {event_id}")
        for v, c in rows:
            embed.add_field(name=v, value=f"{c} slots")

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="slothistory")
    async def slothistory(self, interaction: discord.Interaction, event_id: int):
        async with aiosqlite.connect(DB_NAME) as db:
            rows = await db.execute_fetchall("""
            SELECT h.slot_number, h.vtc_name, h.action, h.timestamp
            FROM history h JOIN panels p ON h.panel_id=p.id
            WHERE p.event_id=? ORDER BY h.id DESC LIMIT 10
            """, (event_id,))

        embed = discord.Embed(title=f"📜 Event {event_id}")
        for s, v, a, t in rows:
            embed.add_field(name=f"Slot {s}", value=f"{v} • {a}")

        await interaction.response.send_message(embed=embed)

    # BOOKING + REFRESH (same as before)
    async def process_booking(self, interaction, panel_id, slot_number,
                              vtc_name, vtc_url, position, member_count):

        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("""
                UPDATE slots SET status='pending', booked_by=?, vtc_name=?, vtc_url=?, position=?, member_count=?
                WHERE panel_id=? AND slot_number=?
            """, (interaction.user.id, vtc_name, vtc_url, position, member_count, panel_id, slot_number))
            await db.commit()

        await interaction.response.send_message("🟡 Sent for approval", ephemeral=True)

        channel = self.bot.get_channel(STAFF_CHANNEL_ID)
        if channel:
            role = interaction.guild.get_role(STAFF_ROLE_ID)
            mention = role.mention if role else "@Staff"

            embed = discord.Embed(title="📥 Booking Request")
            embed.add_field(name="User", value=interaction.user.mention)
            embed.add_field(name="Slot", value=str(slot_number))
            embed.add_field(name="VTC", value=vtc_name)
            embed.add_field(name="URL", value=vtc_url)
            embed.add_field(name="Position", value=position)
            embed.add_field(name="Members", value=str(member_count))

            await channel.send(
                content=mention,
                embed=embed,
                view=StaffApproveView(panel_id, slot_number),
                allowed_mentions=discord.AllowedMentions(roles=True)
            )

    async def refresh_panel(self, panel_id):
        pass


async def setup(bot):
    await bot.add_cog(SlotBooking(bot))
