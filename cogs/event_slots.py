import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiosqlite
import aiohttp
from datetime import datetime

DB_NAME = "slots.db"
STAFF_CHANNEL_ID = 1465720466420269121


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

        options = []

        for s, status, vtc in slots:
            if status == "open":
                options.append(
                    discord.SelectOption(
                        label=f"Slot {s}",
                        description="Available",
                        value=str(s)
                    )
                )

        if not options:
            options.append(
                discord.SelectOption(
                    label="No slots available",
                    value="none",
                    default=True
                )
            )

        super().__init__(
            placeholder="Select a slot...",
            options=options,
            min_values=1,
            max_values=1
        )

        self.panel_id = panel_id

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            return await interaction.response.send_message("❌ No slots", ephemeral=True)

        slot_number = int(self.values[0])
        cog = interaction.client.get_cog("SlotBooking")

        await interaction.response.send_modal(
            BookingModal(cog, self.panel_id, slot_number)
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

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, _):

        async with aiosqlite.connect(DB_NAME) as db:

            cursor = await db.execute(
                "SELECT booked_by, vtc_name FROM slots WHERE panel_id=? AND slot_number=?",
                (self.panel_id, self.slot_number)
            )
            user_id, vtc_name = await cursor.fetchone()

            cursor = await db.execute(
                "SELECT event_id, slot_image FROM panels WHERE id=?",
                (self.panel_id,)
            )
            event_id, slot_image = await cursor.fetchone()

            cursor = await db.execute(
                "SELECT event_name FROM events WHERE event_id=?",
                (event_id,)
            )
            event = await cursor.fetchone()
            event_name = event[0] if event else "Unknown Event"

            await db.execute(
                "UPDATE slots SET status='booked' WHERE panel_id=? AND slot_number=?",
                (self.panel_id, self.slot_number)
            )

            await db.execute(
                "INSERT INTO history VALUES (NULL,?,?,?,?, 'approved', strftime('%s','now'))",
                (self.panel_id, self.slot_number, user_id, vtc_name)
            )

            await db.commit()

        # DM
        user = interaction.client.get_user(user_id)
        if user:
            try:
                embed = discord.Embed(title="✅ Slot Approved", color=discord.Color.green())
                embed.add_field(name="Event", value=event_name, inline=False)
                embed.add_field(name="Slot", value=f"Slot {self.slot_number}")
                embed.add_field(name="VTC", value=vtc_name)
                if slot_image:
                    embed.set_image(url=slot_image)
                await user.send(embed=embed)
            except:
                pass

        await interaction.response.send_message("✅ Approved", ephemeral=True)
        await interaction.client.get_cog("SlotBooking").refresh_panel(self.panel_id)

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, _):
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "UPDATE slots SET status='open', booked_by=NULL WHERE panel_id=? AND slot_number=?",
                (self.panel_id, self.slot_number)
            )
            await db.commit()

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

    def build_slot_text(self, slots):
        lines = []
        for s, status, vtc in slots:
            if status == "open":
                lines.append(f"🅿️ Slot {s}: Available")
            elif status == "pending":
                lines.append(f"🟡 Slot {s}: Pending")
            elif status == "booked":
                lines.append(f"🔴 Slot {s}: {vtc}")
        return "\n".join(lines)

    @tasks.loop(seconds=10)
    async def auto_refresh(self):
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute("SELECT id FROM panels WHERE message_id IS NOT NULL")
            panels = await cursor.fetchall()

        for (pid,) in panels:
            await self.refresh_panel(pid)

    # COMMANDS
    @app_commands.command(name="importevent")
    async def importevent(self, interaction: discord.Interaction, event_id: int):
        await interaction.response.defer(ephemeral=True)

        async with aiohttp.ClientSession() as s:
            async with s.get(f"https://api.truckersmp.com/v2/events/{event_id}") as r:
                data = await r.json()
                e = data["response"]

        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "INSERT INTO events VALUES (NULL,?,?,?,?)",
                (interaction.guild_id, event_id, e["name"],
                 int(datetime.fromisoformat(e["start_at"].replace("Z","+00:00")).timestamp()))
            )
            await db.commit()

        await interaction.followup.send("✅ Event imported", ephemeral=True)

    @app_commands.command(name="createpanel")
    async def createpanel(self, interaction: discord.Interaction,
                          event_id: int, panel_name: str,
                          start_slot: int, end_slot: int,
                          slot_image: str):

        await interaction.response.defer(ephemeral=True)

        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute(
                "INSERT INTO panels VALUES (NULL,?,?,?,NULL,NULL)",
                (event_id, panel_name, slot_image)
            )
            pid = cursor.lastrowid

            for i in range(start_slot, end_slot + 1):
                await db.execute("INSERT INTO slots (panel_id, slot_number) VALUES (?,?)", (pid, i))

            await db.commit()

        await interaction.followup.send(f"✅ Panel created ID: {pid}", ephemeral=True)

    @app_commands.command(name="sendpanel")
    async def sendpanel(self, interaction: discord.Interaction, panel_id: int):
        await interaction.response.defer(ephemeral=True)

        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute("SELECT panel_name, slot_image FROM panels WHERE id=?", (panel_id,))
            panel = await cursor.fetchone()

            cursor = await db.execute(
                "SELECT slot_number, status, vtc_name FROM slots WHERE panel_id=?",
                (panel_id,)
            )
            slots = await cursor.fetchall()

        embed = discord.Embed(
            title=panel[0],
            description=self.build_slot_text(slots),
            color=discord.Color.blue()
        )

        if panel[1]:
            embed.set_image(url=panel[1])

        msg = await interaction.channel.send(embed=embed, view=SlotView(panel_id, slots))

        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "UPDATE panels SET message_id=?, channel_id=? WHERE id=?",
                (msg.id, interaction.channel.id, panel_id)
            )
            await db.commit()

        await interaction.followup.send("✅ Panel sent", ephemeral=True)

    @app_commands.command(name="leaderboard")
    async def leaderboard(self, interaction: discord.Interaction, event_id: int):
        async with aiosqlite.connect(DB_NAME) as db:
            rows = await db.execute_fetchall("""
            SELECT h.vtc_name, COUNT(*) FROM history h
            JOIN panels p ON h.panel_id=p.id
            WHERE h.action='approved' AND p.event_id=?
            GROUP BY h.vtc_name ORDER BY COUNT(*) DESC LIMIT 10
            """, (event_id,))

        embed = discord.Embed(title=f"🏆 Event {event_id}", color=discord.Color.gold())
        for i, (v, t) in enumerate(rows, 1):
            embed.add_field(name=f"{i}. {v}", value=f"{t} slots")

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="slothistory")
    async def slothistory(self, interaction: discord.Interaction, event_id: int):
        async with aiosqlite.connect(DB_NAME) as db:
            rows = await db.execute_fetchall("""
            SELECT h.slot_number, h.vtc_name, h.action, h.timestamp
            FROM history h JOIN panels p ON h.panel_id=p.id
            WHERE p.event_id=? ORDER BY h.id DESC LIMIT 10
            """, (event_id,))

        embed = discord.Embed(title=f"📜 Event {event_id}", color=discord.Color.blue())
        for s, v, a, t in rows:
            embed.add_field(name=f"Slot {s} • {v}", value=f"{a} <t:{t}:R>", inline=False)

        await interaction.response.send_message(embed=embed)

    async def process_booking(self, interaction, panel_id, slot_number,
                              vtc_name, vtc_url, position, member_count):

        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute(
                "SELECT status FROM slots WHERE panel_id=? AND slot_number=?",
                (panel_id, slot_number)
            )
            slot = await cursor.fetchone()

            if not slot or slot[0] != "open":
                return await interaction.response.send_message("❌ Slot taken", ephemeral=True)

            await db.execute(
                "UPDATE slots SET status='pending', booked_by=?, vtc_name=?, vtc_url=?, position=?, member_count=? WHERE panel_id=? AND slot_number=?",
                (interaction.user.id, vtc_name, vtc_url, position, member_count, panel_id, slot_number)
            )
            await db.commit()

        await interaction.response.send_message("🟡 Sent for approval", ephemeral=True)

        channel = self.bot.get_channel(STAFF_CHANNEL_ID)
        if channel:
            embed = discord.Embed(title="📥 Booking Request", color=discord.Color.orange())
            embed.add_field(name="User", value=interaction.user.mention)
            embed.add_field(name="Slot", value=f"Slot {slot_number}")
            embed.add_field(name="VTC", value=vtc_name)

            await channel.send(embed=embed, view=StaffApproveView(panel_id, slot_number))

        await self.refresh_panel(panel_id)

    async def refresh_panel(self, panel_id):
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute(
                "SELECT message_id, channel_id FROM panels WHERE id=?",
                (panel_id,)
            )
            panel = await cursor.fetchone()

            cursor = await db.execute(
                "SELECT slot_number, status, vtc_name FROM slots WHERE panel_id=?",
                (panel_id,)
            )
            slots = await cursor.fetchall()

        channel = self.bot.get_channel(panel[1])
        if channel:
            try:
                msg = await channel.fetch_message(panel[0])
                embed = msg.embeds[0]
                embed.description = self.build_slot_text(slots)
                await msg.edit(embed=embed, view=SlotView(panel_id, slots))
            except:
                pass


async def setup(bot):
    await bot.add_cog(SlotBooking(bot))
