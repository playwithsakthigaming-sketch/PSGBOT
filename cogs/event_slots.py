import discord
from discord.ext import commands
from discord import app_commands
import aiosqlite
from datetime import datetime

DB_NAME = "event_slots.db"

# Replace with your real staff role ID
STAFF_ROLE_ID = 1464425870675411064


# ===============================
# BOOKING MODAL
# ===============================
class BookingModal(discord.ui.Modal):
    def __init__(self, cog, slot_id, slot_no, image, staff_channel):
        super().__init__(title=f"Book Slot {slot_no}")
        self.cog = cog
        self.slot_id = slot_id
        self.slot_no = slot_no
        self.image = image
        self.staff_channel = staff_channel

        self.vtc_name = discord.ui.TextInput(label="VTC Name")
        self.vtc_role = discord.ui.TextInput(label="Your Role")
        self.vtc_link = discord.ui.TextInput(label="VTC Link")
        self.driver_count = discord.ui.TextInput(label="Driver Count")

        self.add_item(self.vtc_name)
        self.add_item(self.vtc_role)
        self.add_item(self.vtc_link)
        self.add_item(self.driver_count)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            driver_count = int(self.driver_count.value)
        except:
            return await interaction.followup.send(
                "❌ Driver count must be a number.",
                ephemeral=True
            )

        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute(
                "SELECT status FROM event_slots WHERE id=?",
                (self.slot_id,)
            )
            row = await cur.fetchone()

            if not row:
                return await interaction.followup.send(
                    "❌ Slot not found.",
                    ephemeral=True
                )

            if row[0] != "free":
                return await interaction.followup.send(
                    "❌ Slot already booked.",
                    ephemeral=True
                )

            await db.execute(
                """
                UPDATE event_slots
                SET booked_by=?, vtc_name=?, vtc_role=?,
                    vtc_link=?, driver_count=?, status='pending',
                    booked_at=?
                WHERE id=?
                """,
                (
                    interaction.user.id,
                    self.vtc_name.value,
                    self.vtc_role.value,
                    self.vtc_link.value,
                    driver_count,
                    datetime.utcnow(),
                    self.slot_id
                )
            )
            await db.commit()

        await interaction.followup.send(
            "⏳ Booking sent for staff approval.",
            ephemeral=True
        )

        staff_ch = interaction.guild.get_channel(self.staff_channel)
        if staff_ch:
            embed = discord.Embed(
                title=f"Slot {self.slot_no} Booking Request",
                color=discord.Color.orange()
            )
            embed.add_field(name="User", value=interaction.user.mention)
            embed.add_field(name="VTC", value=self.vtc_name.value)
            embed.add_field(name="Drivers", value=str(driver_count))
            embed.set_image(url=self.image)

            view = StaffView(self.cog, self.slot_id, interaction.user.id, self.image)
            await staff_ch.send(embed=embed, view=view)


# ===============================
# STAFF VIEW
# ===============================
class StaffView(discord.ui.View):
    def __init__(self, cog, slot_id, user_id, image):
        super().__init__(timeout=None)
        self.cog = cog
        self.slot_id = slot_id
        self.user_id = user_id
        self.image = image

    async def interaction_check(self, interaction: discord.Interaction):
        if any(role.id == STAFF_ROLE_ID for role in interaction.user.roles):
            return True

        await interaction.response.send_message(
            "❌ You are not event staff.",
            ephemeral=True
        )
        return False

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.green)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "UPDATE event_slots SET status='approved' WHERE id=?",
                (self.slot_id,)
            )
            await db.commit()

        user = interaction.guild.get_member(self.user_id)
        if user:
            embed = discord.Embed(title="Slot Approved", color=discord.Color.green())
            embed.set_image(url=self.image)
            try:
                await user.send(embed=embed)
            except:
                pass

        await interaction.followup.send("✅ Slot approved.", ephemeral=True)
        await self.cog.update_embeds(interaction.guild)

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.red)
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "UPDATE event_slots SET status='free', booked_by=NULL WHERE id=?",
                (self.slot_id,)
            )
            await db.commit()

        await interaction.followup.send("❌ Slot rejected.", ephemeral=True)
        await self.cog.update_embeds(interaction.guild)


# ===============================
# SLOT BUTTON
# ===============================
class SlotButton(discord.ui.Button):
    def __init__(self, cog, slot_id, slot_no, image, staff_channel):
        super().__init__(label=f"Slot {slot_no}", style=discord.ButtonStyle.blurple)
        self.cog = cog
        self.slot_id = slot_id
        self.slot_no = slot_no
        self.image = image
        self.staff_channel = staff_channel

    async def callback(self, interaction: discord.Interaction):
        modal = BookingModal(
            self.cog,
            self.slot_id,
            self.slot_no,
            self.image,
            self.staff_channel
        )
        await interaction.response.send_modal(modal)


class SlotView(discord.ui.View):
    def __init__(self, buttons):
        super().__init__(timeout=None)
        for b in buttons:
            self.add_item(b)


# ===============================
# MAIN COG
# ===============================
class EventSlots(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.panel_messages = {}
        bot.loop.create_task(self.init_db())

    async def init_db(self):
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("""
            CREATE TABLE IF NOT EXISTS event_locations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                event_id TEXT,
                location_name TEXT,
                image_url TEXT
            )
            """)

            await db.execute("""
            CREATE TABLE IF NOT EXISTS event_slots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                event_id TEXT,
                location_id INTEGER,
                slot_no INTEGER,
                status TEXT DEFAULT 'free',
                booked_by INTEGER,
                vtc_name TEXT,
                vtc_role TEXT,
                vtc_link TEXT,
                driver_count INTEGER,
                booked_at TEXT
            )
            """)
            await db.commit()

    # ---------------------------
    # ADD LOCATION
    # ---------------------------
    @app_commands.command(name="addlocation")
    @app_commands.checks.has_permissions(administrator=True)
    async def addlocation(
        self,
        interaction: discord.Interaction,
        event_id: str,
        name: str,
        image: str,
        slots: str,
        staff_channel: discord.TextChannel
    ):
        await interaction.response.defer()

        slot_list = [int(s.strip()) for s in slots.split(",")]
        buttons = []

        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute(
                """
                INSERT INTO event_locations
                (guild_id, event_id, location_name, image_url)
                VALUES (?, ?, ?, ?)
                """,
                (interaction.guild_id, event_id, name, image)
            )
            location_id = cur.lastrowid

            for slot in slot_list:
                cur = await db.execute(
                    """
                    INSERT INTO event_slots
                    (guild_id, event_id, location_id, slot_no)
                    VALUES (?, ?, ?, ?)
                    """,
                    (interaction.guild_id, event_id, location_id, slot)
                )
                slot_id = cur.lastrowid
                buttons.append(SlotButton(self, slot_id, slot, image, staff_channel.id))

            await db.commit()

        slot_text = "\n".join(
            [f"🅿️ Slot {s}: *Available*" for s in slot_list]
        )

        embed = discord.Embed(
            title=name,
            description=slot_text,
            color=discord.Color.blue()
        )
        embed.set_image(url=image)

        view = SlotView(buttons)
        msg = await interaction.followup.send(embed=embed, view=view)
        self.panel_messages[interaction.guild_id] = msg

    # ---------------------------
    # SHOW SLOTS
    # ---------------------------
    @app_commands.command(name="showslots")
    async def showslots(self, interaction: discord.Interaction, event_id: str):
        await interaction.response.defer()

        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute(
                "SELECT slot_no, status FROM event_slots WHERE event_id=?",
                (event_id,)
            )
            rows = await cur.fetchall()

        text = ""
        for slot, status in rows:
            state = (
                "Available" if status == "free"
                else "Pending" if status == "pending"
                else "Booked"
            )
            text += f"🅿️ Slot {slot}: *{state}*\n"

        embed = discord.Embed(title="Slot Status", description=text)
        await interaction.followup.send(embed=embed)

    # ---------------------------
    # RESET SLOT
    # ---------------------------
    @app_commands.command(name="resetslot")
    @app_commands.checks.has_permissions(administrator=True)
    async def resetslot(self, interaction: discord.Interaction, slot_id: int):
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "UPDATE event_slots SET status='free', booked_by=NULL WHERE id=?",
                (slot_id,)
            )
            await db.commit()

        await interaction.response.send_message("♻️ Slot reset.", ephemeral=True)

    async def update_embeds(self, guild):
        msg = self.panel_messages.get(guild.id)
        if not msg:
            return

        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute(
                "SELECT slot_no, status FROM event_slots WHERE guild_id=?",
                (guild.id,)
            )
            rows = await cur.fetchall()

        text = ""
        for slot, status in rows:
            state = (
                "Available" if status == "free"
                else "Pending" if status == "pending"
                else "Booked"
            )
            text += f"🅿️ Slot {slot}: *{state}*\n"

        embed = msg.embeds[0]
        embed.description = text
        await msg.edit(embed=embed)


async def setup(bot):
    await bot.add_cog(EventSlots(bot))
