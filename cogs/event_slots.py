import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiosqlite
import aiohttp
import os
import time
from datetime import datetime

DB_NAME = "slots.db"
STAFF_CHANNEL_ID = int(os.getenv("STAFF_CHANNEL_ID", 0))


# ===============================
# DATABASE SETUP
# ===============================
async def setup_database():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            event_id INTEGER,
            event_name TEXT,
            event_time INTEGER
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS panels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER,
            panel_name TEXT,
            slot_image TEXT,
            message_id INTEGER,
            channel_id INTEGER
        )
        """)

        await db.execute("""
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
        )
        """)
        await db.commit()


# ===============================
# BOOKING MODAL
# ===============================
class BookingModal(discord.ui.Modal, title="Slot Booking Form"):
    def __init__(self, cog, panel_id, slot_number):
        super().__init__()
        self.cog = cog
        self.panel_id = panel_id
        self.slot_number = slot_number

        self.vtc_name = discord.ui.TextInput(label="VTC Name", required=True)
        self.vtc_url = discord.ui.TextInput(label="VTC URL", required=True)
        self.position = discord.ui.TextInput(label="Your VTC Position", required=True)
        self.member_count = discord.ui.TextInput(label="Attending Member Count", required=True)

        self.add_item(self.vtc_name)
        self.add_item(self.vtc_url)
        self.add_item(self.position)
        self.add_item(self.member_count)

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.process_booking(
            interaction,
            self.panel_id,
            self.slot_number,
            self.vtc_name.value,
            self.vtc_url.value,
            self.position.value,
            self.member_count.value
        )


# ===============================
# SLOT BUTTON
# ===============================
class SlotButton(discord.ui.Button):
    def __init__(self, panel_id, slot_number, status):
        if status == "open":
            style = discord.ButtonStyle.success
            disabled = False
        elif status == "pending":
            style = discord.ButtonStyle.primary
            disabled = True
        else:
            style = discord.ButtonStyle.danger
            disabled = True

        super().__init__(label=str(slot_number), style=style, disabled=disabled)
        self.panel_id = panel_id
        self.slot_number = slot_number

    async def callback(self, interaction: discord.Interaction):
        cog: SlotBooking = interaction.client.get_cog("SlotBooking")
        modal = BookingModal(cog, self.panel_id, self.slot_number)
        await interaction.response.send_modal(modal)


class SlotView(discord.ui.View):
    def __init__(self, panel_id, slots):
        super().__init__(timeout=None)
        for slot_number, status in slots:
            if status == "booked":
                continue
            self.add_item(SlotButton(panel_id, slot_number, status))


# ===============================
# STAFF VIEW
# ===============================
class StaffApproveView(discord.ui.View):
    def __init__(self, panel_id, slot_number, user_id):
        super().__init__(timeout=None)
        self.panel_id = panel_id
        self.slot_number = slot_number
        self.user_id = user_id

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "UPDATE slots SET status='booked' WHERE panel_id=? AND slot_number=?",
                (self.panel_id, self.slot_number)
            )
            await db.commit()

        await interaction.response.send_message("Approved.", ephemeral=True)

        cog = interaction.client.get_cog("SlotBooking")
        await cog.refresh_panel(self.panel_id)

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "UPDATE slots SET status='open', booked_by=NULL WHERE panel_id=? AND slot_number=?",
                (self.panel_id, self.slot_number)
            )
            await db.commit()

        await interaction.response.send_message("Rejected.", ephemeral=True)

        cog = interaction.client.get_cog("SlotBooking")
        await cog.refresh_panel(self.panel_id)


# ===============================
# MAIN COG
# ===============================
class SlotBooking(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        bot.loop.create_task(setup_database())

    # -----------------------------
    # IMPORT EVENT
    # -----------------------------
    @app_commands.command(name="importevent")
    async def importevent(self, interaction: discord.Interaction, event_id: int):
        await interaction.response.defer()

        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://api.truckersmp.com/v2/events/{event_id}") as resp:
                data = await resp.json()
                event = data["response"]
                event_name = event["name"]
                event_time = int(
                    datetime.fromisoformat(event["start_at"].replace("Z", "+00:00")).timestamp()
                )

        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "INSERT INTO events (guild_id, event_id, event_name, event_time) VALUES (?, ?, ?, ?)",
                (interaction.guild_id, event_id, event_name, event_time)
            )
            await db.commit()

        await interaction.followup.send(f"✅ Event **{event_name}** imported.")

    # -----------------------------
    # CREATE PANEL
    # -----------------------------
    @app_commands.command(name="createpanel")
    async def createpanel(self, interaction: discord.Interaction,
                          event_id: int, panel_name: str,
                          start_slot: int, end_slot: int,
                          slot_image: str):
        await interaction.response.defer()

        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute(
                "INSERT INTO panels (event_id, panel_name, slot_image) VALUES (?, ?, ?)",
                (event_id, panel_name, slot_image)
            )
            panel_id = cursor.lastrowid

            for i in range(start_slot, end_slot + 1):
                await db.execute(
                    "INSERT INTO slots (panel_id, slot_number) VALUES (?, ?)",
                    (panel_id, i)
                )

            await db.commit()

        await interaction.followup.send(
            f"✅ Panel **{panel_name}** created.\nPanel ID: `{panel_id}`"
        )

    # -----------------------------
    # SEND PANEL (FIXED)
    # -----------------------------
    @app_commands.command(name="sendpanel")
    async def sendpanel(self, interaction: discord.Interaction, panel_id: int):
        await interaction.response.defer(ephemeral=True)

        try:
            async with aiosqlite.connect(DB_NAME) as db:
                cursor = await db.execute(
                    "SELECT panel_name, slot_image, event_id FROM panels WHERE id=?",
                    (panel_id,)
                )
                panel = await cursor.fetchone()

                if not panel:
                    return await interaction.followup.send("❌ Panel not found.", ephemeral=True)

                panel_name, slot_image, event_id = panel

                cursor = await db.execute(
                    "SELECT event_name FROM events WHERE event_id=?",
                    (event_id,)
                )
                event = await cursor.fetchone()

                if not event:
                    return await interaction.followup.send(
                        "❌ Event not found. Run /importevent again.",
                        ephemeral=True
                    )

                event_name = event[0]

                cursor = await db.execute(
                    "SELECT slot_number, status FROM slots WHERE panel_id=? ORDER BY slot_number",
                    (panel_id,)
                )
                slots = await cursor.fetchall()

            embed = discord.Embed(
                title=f"{event_name} — {panel_name}",
                description="Click a slot to book.",
                color=discord.Color.blue()
            )

            if slot_image:
                embed.set_image(url=slot_image)

            view = SlotView(panel_id, slots)
            msg = await interaction.channel.send(embed=embed, view=view)

            async with aiosqlite.connect(DB_NAME) as db:
                await db.execute(
                    "UPDATE panels SET message_id=?, channel_id=? WHERE id=?",
                    (msg.id, interaction.channel.id, panel_id)
                )
                await db.commit()

            await interaction.followup.send(
                f"✅ Panel sent successfully.\nPanel ID: `{panel_id}`",
                ephemeral=True
            )

        except Exception as e:
            await interaction.followup.send(
                f"❌ Send panel error:\n`{str(e)}`",
                ephemeral=True
            )

    # -----------------------------
    # PROCESS BOOKING
    # -----------------------------
    async def process_booking(self, interaction, panel_id, slot_number,
                              vtc_name, vtc_url, position, member_count):
        await interaction.response.send_message(
            f"🟡 Slot {slot_number} request submitted.",
            ephemeral=True
        )

    async def refresh_panel(self, panel_id):
        pass


async def setup(bot):
    await bot.add_cog(SlotBooking(bot))
