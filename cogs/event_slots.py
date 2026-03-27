import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiosqlite
import aiohttp
import os
from datetime import datetime

DB_NAME = "slots.db"
STAFF_CHANNEL_ID = int(os.getenv("STAFF_CHANNEL_ID", 0))


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

        self.vtc_name = discord.ui.TextInput(label="VTC Name")
        self.vtc_url = discord.ui.TextInput(label="VTC URL")
        self.position = discord.ui.TextInput(label="Position")
        self.member_count = discord.ui.TextInput(label="Member Count")

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
# BUTTON
# ===============================
class SlotButton(discord.ui.Button):
    def __init__(self, panel_id, slot_number, status):
        style = discord.ButtonStyle.success
        disabled = False

        if status == "pending":
            style = discord.ButtonStyle.primary
            disabled = True
        elif status == "booked":
            style = discord.ButtonStyle.danger
            disabled = True

        super().__init__(label=f"Slot {slot_number}", style=style, disabled=disabled)

        self.panel_id = panel_id
        self.slot_number = slot_number

    async def callback(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog("SlotBooking")
        await interaction.response.send_modal(
            BookingModal(cog, self.panel_id, self.slot_number)
        )


class SlotView(discord.ui.View):
    def __init__(self, panel_id, slots):
        super().__init__(timeout=None)
        for s, status in slots:
            self.add_item(SlotButton(panel_id, s, status))


# ===============================
# STAFF
# ===============================
class StaffApproveView(discord.ui.View):
    def __init__(self, panel_id, slot_number):
        super().__init__(timeout=None)
        self.panel_id = panel_id
        self.slot_number = slot_number

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, _):
        async with aiosqlite.connect(DB_NAME) as db:
            slot = await db.execute_fetchone(
                "SELECT booked_by, vtc_name FROM slots WHERE panel_id=? AND slot_number=?",
                (self.panel_id, self.slot_number)
            )

            await db.execute(
                "UPDATE slots SET status='booked' WHERE panel_id=? AND slot_number=?",
                (self.panel_id, self.slot_number)
            )

            await db.execute(
                "INSERT INTO history VALUES (NULL,?,?,?,?, 'approved', strftime('%s','now'))",
                (self.panel_id, self.slot_number, slot[0], slot[1])
            )

            await db.commit()

        await interaction.response.send_message("✅ Approved", ephemeral=True)
        await interaction.client.get_cog("SlotBooking").refresh_panel(self.panel_id)

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, _):
        async with aiosqlite.connect(DB_NAME) as db:
            slot = await db.execute_fetchone(
                "SELECT booked_by, vtc_name FROM slots WHERE panel_id=? AND slot_number=?",
                (self.panel_id, self.slot_number)
            )

            await db.execute(
                "UPDATE slots SET status='open', booked_by=NULL WHERE panel_id=? AND slot_number=?",
                (self.panel_id, self.slot_number)
            )

            await db.execute(
                "INSERT INTO history VALUES (NULL,?,?,?,?, 'rejected', strftime('%s','now'))",
                (self.panel_id, self.slot_number, slot[0], slot[1])
            )

            await db.commit()

        await interaction.response.send_message("❌ Rejected", ephemeral=True)
        await interaction.client.get_cog("SlotBooking").refresh_panel(self.panel_id)


# ===============================
# COG
# ===============================
class SlotBooking(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        bot.loop.create_task(setup_database())
        self.auto_refresh.start()

    def cog_unload(self):
        self.auto_refresh.cancel()

    # AUTO REFRESH EVERY 10s
    @tasks.loop(seconds=10)
    async def auto_refresh(self):
        async with aiosqlite.connect(DB_NAME) as db:
            panels = await db.execute_fetchall(
                "SELECT id FROM panels WHERE message_id IS NOT NULL"
            )

        for (panel_id,) in panels:
            try:
                await self.refresh_panel(panel_id)
            except Exception as e:
                print(f"[AutoRefresh Error] {panel_id}: {e}")

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
        event_time = int(datetime.fromisoformat(event["start_at"].replace("Z","+00:00")).timestamp())

        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "INSERT INTO events VALUES (NULL,?,?,?,?)",
                (interaction.guild_id, event_id, event_name, event_time)
            )
            await db.commit()

        await interaction.followup.send(f"✅ Imported {event_name}")

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
            cur = await db.execute(
                "INSERT INTO panels VALUES (NULL,?,?,?,NULL,NULL)",
                (event_id, panel_name, slot_image)
            )
            panel_id = cur.lastrowid

            for i in range(start_slot, end_slot+1):
                await db.execute(
                    "INSERT INTO slots (panel_id, slot_number) VALUES (?,?)",
                    (panel_id, i)
                )

            await db.commit()

        await interaction.followup.send(f"✅ Panel created ID: {panel_id}")

    # -----------------------------
    # SEND PANEL
    # -----------------------------
    @app_commands.command(name="sendpanel")
    async def sendpanel(self, interaction: discord.Interaction, panel_id: int):

        await interaction.response.defer(ephemeral=True)

        try:
            async with aiosqlite.connect(DB_NAME) as db:

                cur = await db.execute(
                    "SELECT panel_name, slot_image FROM panels WHERE id=?",
                    (panel_id,)
                )
                panel = await cur.fetchone()

                if not panel:
                    return await interaction.followup.send("❌ Panel not found", ephemeral=True)

                panel_name, slot_image = panel

                cur = await db.execute(
                    "SELECT slot_number, status FROM slots WHERE panel_id=? ORDER BY slot_number",
                    (panel_id,)
                )
                slots = await cur.fetchall()

            embed = discord.Embed(title=panel_name, description="Click a slot to book", color=discord.Color.blue())

            if slot_image:
                embed.set_image(url=slot_image)

            msg = await interaction.channel.send(embed=embed, view=SlotView(panel_id, slots))

            async with aiosqlite.connect(DB_NAME) as db:
                await db.execute(
                    "UPDATE panels SET message_id=?, channel_id=? WHERE id=?",
                    (msg.id, interaction.channel.id, panel_id)
                )
                await db.commit()

            await interaction.followup.send(f"✅ Panel sent (ID: {panel_id})", ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"❌ Error:\n`{e}`", ephemeral=True)

    # -----------------------------
    # LEADERBOARD
    # -----------------------------
    @app_commands.command(name="leaderboard")
    async def leaderboard(self, interaction: discord.Interaction):
        async with aiosqlite.connect(DB_NAME) as db:
            rows = await db.execute_fetchall("""
                SELECT vtc_name, COUNT(*) FROM history
                WHERE action='approved'
                GROUP BY vtc_name ORDER BY COUNT(*) DESC LIMIT 10
            """)

        embed = discord.Embed(title="🏆 Leaderboard", color=discord.Color.gold())

        for i, (vtc, total) in enumerate(rows, 1):
            embed.add_field(name=f"{i}. {vtc}", value=f"{total} slots")

        await interaction.response.send_message(embed=embed)

    # -----------------------------
    # SLOT HISTORY
    # -----------------------------
    @app_commands.command(name="slothistory")
    async def slothistory(self, interaction: discord.Interaction):
        async with aiosqlite.connect(DB_NAME) as db:
            rows = await db.execute_fetchall("""
                SELECT slot_number, vtc_name, action, timestamp
                FROM history ORDER BY id DESC LIMIT 10
            """)

        embed = discord.Embed(title="📜 Slot History", color=discord.Color.blue())

        for s, v, a, t in rows:
            embed.add_field(
                name=f"Slot {s} - {v}",
                value=f"{a.upper()} <t:{t}:R>",
                inline=False
            )

        await interaction.response.send_message(embed=embed)

    # -----------------------------
    # BOOKING
    # -----------------------------
    async def process_booking(self, interaction, panel_id, slot_number,
                              vtc_name, vtc_url, position, member_count):

        async with aiosqlite.connect(DB_NAME) as db:

            existing = await db.execute_fetchone(
                "SELECT id FROM slots WHERE panel_id=? AND booked_by=? AND status='pending'",
                (panel_id, interaction.user.id)
            )

            if existing:
                return await interaction.response.send_message("❌ Already requested", ephemeral=True)

            slot = await db.execute_fetchone(
                "SELECT status FROM slots WHERE panel_id=? AND slot_number=?",
                (panel_id, slot_number)
            )

            if slot[0] != "open":
                return await interaction.response.send_message("❌ Slot taken", ephemeral=True)

            await db.execute(
                "UPDATE slots SET status='pending', booked_by=?, vtc_name=?, vtc_url=?, position=?, member_count=? WHERE panel_id=? AND slot_number=?",
                (interaction.user.id, vtc_name, vtc_url, position, int(member_count), panel_id, slot_number)
            )

            await db.commit()

        await interaction.response.send_message("🟡 Sent for approval", ephemeral=True)

        if STAFF_CHANNEL_ID:
            ch = self.bot.get_channel(STAFF_CHANNEL_ID)
            if ch:
                embed = discord.Embed(title="New Booking")
                embed.add_field(name="User", value=interaction.user.mention)
                embed.add_field(name="Slot", value=f"Slot {slot_number}")
                embed.add_field(name="VTC", value=vtc_name)

                await ch.send(embed=embed, view=StaffApproveView(panel_id, slot_number))

        await self.refresh_panel(panel_id)

    # -----------------------------
    # REFRESH PANEL
    # -----------------------------
    async def refresh_panel(self, panel_id):
        async with aiosqlite.connect(DB_NAME) as db:
            panel = await db.execute_fetchone(
                "SELECT message_id, channel_id FROM panels WHERE id=?",
                (panel_id,)
            )

            if not panel:
                return

            slots = await db.execute_fetchall(
                "SELECT slot_number, status FROM slots WHERE panel_id=?",
                (panel_id,)
            )

        channel = self.bot.get_channel(panel[1])
        if not channel:
            return

        try:
            msg = await channel.fetch_message(panel[0])
            await msg.edit(view=SlotView(panel_id, slots))
        except:
            pass


# ===============================
# SETUP
# ===============================
async def setup(bot):
    await bot.add_cog(SlotBooking(bot))
