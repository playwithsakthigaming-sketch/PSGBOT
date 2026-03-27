import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiosqlite
import aiohttp
from datetime import datetime

DB_NAME = "slots.db"
STAFF_CHANNEL_ID = 1465720466420269121
STAFF_ROLE_ID = 1419223859483115591  # CHANGE


# ================= DATABASE =================
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


# ================= MODAL =================
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

        for i in [self.vtc_name, self.vtc_url, self.position, self.member_count]:
            self.add_item(i)

    async def on_submit(self, interaction):
        await self.cog.process_booking(
            interaction,
            self.panel_id,
            self.slot_number,
            self.vtc_name.value,
            self.vtc_url.value,
            self.position.value,
            int(self.member_count.value)
        )


# ================= DROPDOWN =================
class SlotSelect(discord.ui.Select):
    def __init__(self, panel_id, slots):
        options = [
            discord.SelectOption(label=f"Slot {s}", value=str(s))
            for s, status, _ in slots if status == "open"
        ] or [discord.SelectOption(label="No slots", value="none")]

        super().__init__(placeholder="Select slot", options=options)
        self.panel_id = panel_id

    async def callback(self, interaction):
        if self.values[0] == "none":
            return await interaction.response.send_message("No slots", ephemeral=True)

        cog = interaction.client.get_cog("SlotBooking")
        await interaction.response.send_modal(
            BookingModal(cog, self.panel_id, int(self.values[0]))
        )


class SlotView(discord.ui.View):
    def __init__(self, panel_id, slots):
        super().__init__(timeout=None)
        self.add_item(SlotSelect(panel_id, slots))


# ================= STAFF VIEW =================
class StaffApproveView(discord.ui.View):
    def __init__(self, panel_id, slot_number):
        super().__init__(timeout=None)
        self.panel_id = panel_id
        self.slot_number = slot_number

    def check(self, interaction):
        return any(r.id == STAFF_ROLE_ID for r in interaction.user.roles)

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success)
    async def approve(self, interaction, _):
        if not self.check(interaction):
            return await interaction.response.send_message("No permission", ephemeral=True)

        async with aiosqlite.connect(DB_NAME) as db:
            user_id = (await (await db.execute(
                "SELECT booked_by FROM slots WHERE panel_id=? AND slot_number=?",
                (self.panel_id, self.slot_number))).fetchone())[0]

            event_id, img = await (await db.execute(
                "SELECT event_id, slot_image FROM panels WHERE id=?",
                (self.panel_id,))).fetchone()

            event_name = (await (await db.execute(
                "SELECT event_name FROM events WHERE event_id=?",
                (event_id,))).fetchone())[0]

            await db.execute("UPDATE slots SET status='booked' WHERE panel_id=? AND slot_number=?",
                             (self.panel_id, self.slot_number))

            await db.execute("INSERT INTO history VALUES (NULL,?,?,?,?, 'approved', strftime('%s','now'))",
                             (self.panel_id, self.slot_number, user_id, ""))

            await db.commit()

        user = interaction.client.get_user(user_id)
        if user:
            embed = discord.Embed(title="✅ Slot Approved")
            embed.add_field(name="Event", value=event_name)
            embed.add_field(name="Slot", value=f"Slot {self.slot_number}")
            if img:
                embed.set_image(url=img)
            await user.send(embed=embed)

        await interaction.message.delete()
        await interaction.response.send_message("Approved", ephemeral=True)

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger)
    async def reject(self, interaction, _):
        if not self.check(interaction):
            return await interaction.response.send_message("No permission", ephemeral=True)

        async with aiosqlite.connect(DB_NAME) as db:
            user_id = (await (await db.execute(
                "SELECT booked_by FROM slots WHERE panel_id=? AND slot_number=?",
                (self.panel_id, self.slot_number))).fetchone())[0]

            event_id = (await (await db.execute(
                "SELECT event_id FROM panels WHERE id=?",
                (self.panel_id,))).fetchone())[0]

            event_name = (await (await db.execute(
                "SELECT event_name FROM events WHERE event_id=?",
                (event_id,))).fetchone())[0]

            await db.execute("UPDATE slots SET status='open', booked_by=NULL WHERE panel_id=? AND slot_number=?",
                             (self.panel_id, self.slot_number))
            await db.commit()

        user = interaction.client.get_user(user_id)
        if user:
            embed = discord.Embed(title="❌ Slot Rejected")
            embed.add_field(name="Event", value=event_name)
            embed.add_field(name="Message", value="Contact event manager")
            await user.send(embed=embed)

        await interaction.message.delete()
        await interaction.response.send_message("Rejected", ephemeral=True)


# ================= MAIN =================
class SlotBooking(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        bot.loop.create_task(setup_database())
        self.auto_refresh.start()

    def cog_unload(self):
        self.auto_refresh.cancel()

    async def cog_app_command_error(self, interaction, error):
        if isinstance(error, app_commands.errors.MissingRole):
            await interaction.response.send_message("No permission", ephemeral=True)

    def build(self, slots):
        return "\n".join(
            f"🅿️ Slot {s}" if st == "open"
            else f"🟡 Slot {s}" if st == "pending"
            else f"🔴 Slot {s}: {v}"
            for s, st, v in slots
        )

    @tasks.loop(seconds=10)
    async def auto_refresh(self):
        async with aiosqlite.connect(DB_NAME) as db:
            panels = await db.execute_fetchall("SELECT id FROM panels WHERE message_id IS NOT NULL")
        for (pid,) in panels:
            await self.refresh_panel(pid)

    # ---------- COMMANDS ----------
    @app_commands.command(name="importevent")
    @app_commands.checks.has_role(STAFF_ROLE_ID)
    async def importevent(self, interaction, event_id: int):
        await interaction.response.defer(ephemeral=True)
        async with aiohttp.ClientSession() as s:
            e = (await (await s.get(f"https://api.truckersmp.com/v2/events/{event_id}")).json())["response"]

        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("INSERT INTO events VALUES (NULL,?,?,?,?)",
                             (interaction.guild_id, event_id, e["name"],
                              int(datetime.fromisoformat(e["start_at"].replace("Z","+00:00")).timestamp())))
            await db.commit()

        await interaction.followup.send("Event imported", ephemeral=True)

    @app_commands.command(name="createpanel")
    @app_commands.checks.has_role(STAFF_ROLE_ID)
    async def createpanel(self, interaction, event_id: int, name: str, start: int, end: int, img: str):
        await interaction.response.defer(ephemeral=True)

        async with aiosqlite.connect(DB_NAME) as db:
            pid = (await db.execute(
                "INSERT INTO panels VALUES (NULL,?,?,?,NULL,NULL)",
                (event_id, name, img)
            )).lastrowid

            for i in range(start, end + 1):
                await db.execute("INSERT INTO slots (panel_id, slot_number) VALUES (?,?)", (pid, i))

            await db.commit()

        await interaction.followup.send(f"Panel ID: {pid}", ephemeral=True)

    @app_commands.command(name="sendpanel")
    @app_commands.checks.has_role(STAFF_ROLE_ID)
    async def sendpanel(self, interaction, panel_id: int):
        await interaction.response.defer(ephemeral=True)

        async with aiosqlite.connect(DB_NAME) as db:
            panel = await (await db.execute(
                "SELECT panel_name, slot_image FROM panels WHERE id=?", (panel_id,)
            )).fetchone()

            slots = await (await db.execute(
                "SELECT slot_number, status, vtc_name FROM slots WHERE panel_id=?", (panel_id,)
            )).fetchall()

        embed = discord.Embed(title=panel[0], description=self.build(slots))
        if panel[1]:
            embed.set_image(url=panel[1])

        msg = await interaction.channel.send(embed=embed, view=SlotView(panel_id, slots))

        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "UPDATE panels SET message_id=?, channel_id=? WHERE id=?",
                (msg.id, interaction.channel.id, panel_id)
            )
            await db.commit()

        await interaction.followup.send("Panel sent", ephemeral=True)

    @app_commands.command(name="leaderboard")
    async def leaderboard(self, interaction, event_id: int):
        async with aiosqlite.connect(DB_NAME) as db:
            rows = await db.execute_fetchall("""
                SELECT vtc_name, COUNT(*) FROM history h
                JOIN panels p ON h.panel_id=p.id
                WHERE p.event_id=? GROUP BY vtc_name
            """, (event_id,))

        embed = discord.Embed(title=f"Leaderboard {event_id}")
        for v, c in rows:
            embed.add_field(name=v, value=f"{c} slots")

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="slothistory")
    async def slothistory(self, interaction, event_id: int):
        async with aiosqlite.connect(DB_NAME) as db:
            rows = await db.execute_fetchall("""
                SELECT h.slot_number, h.vtc_name FROM history h
                JOIN panels p ON h.panel_id=p.id
                WHERE p.event_id=? LIMIT 10
            """, (event_id,))

        embed = discord.Embed(title=f"History {event_id}")
        for s, v in rows:
            embed.add_field(name=f"Slot {s}", value=v)

        await interaction.response.send_message(embed=embed)

    # ---------- BOOK ----------
    async def process_booking(self, interaction, panel_id, slot_number,
                              vtc_name, vtc_url, position, member_count):

        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("""
                UPDATE slots SET status='pending', booked_by=?, vtc_name=?, vtc_url=?, position=?, member_count=?
                WHERE panel_id=? AND slot_number=?
            """, (interaction.user.id, vtc_name, vtc_url, position, member_count, panel_id, slot_number))
            await db.commit()

        await interaction.response.send_message("Sent for approval", ephemeral=True)

        channel = self.bot.get_channel(STAFF_CHANNEL_ID)
        if channel:
            role = interaction.guild.get_role(STAFF_ROLE_ID)
            embed = discord.Embed(title="📥 Booking Request")
            embed.add_field(name="User", value=interaction.user.mention)
            embed.add_field(name="Slot", value=slot_number)
            embed.add_field(name="VTC", value=vtc_name)
            embed.add_field(name="URL", value=vtc_url)

            await channel.send(
                content=role.mention if role else "@Staff",
                embed=embed,
                view=StaffApproveView(panel_id, slot_number),
                allowed_mentions=discord.AllowedMentions(roles=True)
            )

        await self.refresh_panel(panel_id)

    async def refresh_panel(self, panel_id):
        async with aiosqlite.connect(DB_NAME) as db:
            panel = await (await db.execute(
                "SELECT message_id, channel_id FROM panels WHERE id=?", (panel_id,)
            )).fetchone()

            slots = await (await db.execute(
                "SELECT slot_number, status, vtc_name FROM slots WHERE panel_id=?", (panel_id,)
            )).fetchall()

        channel = self.bot.get_channel(panel[1])
        if channel:
            try:
                msg = await channel.fetch_message(panel[0])
                embed = msg.embeds[0]
                embed.description = self.build(slots)
                await msg.edit(embed=embed, view=SlotView(panel_id, slots))
            except:
                pass


async def setup(bot):
    await bot.add_cog(SlotBooking(bot))
