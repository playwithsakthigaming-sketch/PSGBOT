import discord
from discord.ext import commands
from discord import app_commands
from supabase import create_client, Client
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

STAFF_ROLE = "Event Staff"


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
        supabase.table("event_slots").update({
            "booked_by": interaction.user.id,
            "vtc_name": self.vtc_name.value,
            "vtc_role": self.vtc_role.value,
            "vtc_link": self.vtc_link.value,
            "driver_count": int(self.driver_count.value),
            "status": "pending",
            "booked_at": datetime.utcnow().isoformat()
        }).eq("id", self.slot_id).execute()

        await interaction.response.send_message(
            "⏳ Booking sent for staff approval.",
            ephemeral=True
        )

        staff_ch = interaction.guild.get_channel(self.staff_channel)

        embed = discord.Embed(
            title=f"Slot {self.slot_no} Booking Request",
            color=discord.Color.orange()
        )
        embed.add_field(name="User", value=interaction.user.mention)
        embed.add_field(name="VTC", value=self.vtc_name.value)
        embed.add_field(name="Drivers", value=self.driver_count.value)
        embed.set_image(url=self.image)

        view = StaffView(self.cog, self.slot_id, interaction.user.id, self.image)
        await staff_ch.send(embed=embed, view=view)


# ===============================
# STAFF APPROVAL VIEW
# ===============================
class StaffView(discord.ui.View):
    def __init__(self, cog, slot_id, user_id, image):
        super().__init__(timeout=None)
        self.cog = cog
        self.slot_id = slot_id
        self.user_id = user_id
        self.image = image

    async def interaction_check(self, interaction: discord.Interaction):
        # Check staff role by ID
        if any(role.id == STAFF_ROLE_ID for role in interaction.user.roles):
            return True

        await interaction.response.send_message(
            "❌ You are not event staff.",
            ephemeral=True
        )
        return False

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.green)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.defer(ephemeral=True)

            # Update database
            supabase.table("event_slots").update({
                "status": "approved"
            }).eq("id", self.slot_id).execute()

            # DM user
            user = interaction.guild.get_member(self.user_id)
            if user:
                embed = discord.Embed(
                    title="Slot Approved",
                    description="Your slot booking has been approved.",
                    color=discord.Color.green()
                )
                embed.set_image(url=self.image)
                try:
                    await user.send(embed=embed)
                except:
                    pass

            await interaction.followup.send("✅ Slot approved.", ephemeral=True)

            # Update public panel
            await self.cog.update_embeds(interaction.guild)

        except Exception as e:
            print("Approve error:", e)
            await interaction.followup.send(
                "❌ Error approving slot.",
                ephemeral=True
            )

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.red)
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.defer(ephemeral=True)

            supabase.table("event_slots").update({
                "status": "free",
                "booked_by": None
            }).eq("id", self.slot_id).execute()

            await interaction.followup.send("❌ Slot rejected.", ephemeral=True)

            await self.cog.update_embeds(interaction.guild)

        except Exception as e:
            print("Reject error:", e)
            await interaction.followup.send(
                "❌ Error rejecting slot.",
                ephemeral=True
            )


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

    # ---------------------------
    # ADMIN: ADD LOCATION
    # ---------------------------
    @app_commands.command(name="addlocation", description="Create slot panel")
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

        loc = supabase.table("event_locations").insert({
            "guild_id": interaction.guild_id,
            "event_id": event_id,
            "location_name": name,
            "image_url": image
        }).execute()

        location_id = loc.data[0]["id"]

        for slot in slot_list:
            s = supabase.table("event_slots").insert({
                "guild_id": interaction.guild_id,
                "event_id": event_id,
                "location_id": location_id,
                "slot_no": slot
            }).execute()

            slot_id = s.data[0]["id"]

            buttons.append(
                SlotButton(
                    self,
                    slot_id,
                    slot,
                    image,
                    staff_channel.id
                )
            )

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
    # ADMIN: SHOW SLOTS
    # ---------------------------
    @app_commands.command(name="showslots", description="Show slot status")
    async def showslots(self, interaction: discord.Interaction, event_id: str):
        await interaction.response.defer()

        res = supabase.table("event_slots").select(
            "slot_no, status"
        ).eq("guild_id", interaction.guild_id).eq("event_id", event_id).execute()

        text = ""
        for row in res.data:
            state = (
                "Available" if row["status"] == "free"
                else "Pending" if row["status"] == "pending"
                else "Booked"
            )
            text += f"🅿️ Slot {row['slot_no']}: *{state}*\n"

        embed = discord.Embed(
            title="Slot Status",
            description=text,
            color=discord.Color.blue()
        )

        await interaction.followup.send(embed=embed)

    # ---------------------------
    # ADMIN: RESET SLOT
    # ---------------------------
    @app_commands.command(name="resetslot", description="Reset a slot")
    @app_commands.checks.has_permissions(administrator=True)
    async def resetslot(
        self,
        interaction: discord.Interaction,
        slot_id: int
    ):
        supabase.table("event_slots").update({
            "status": "free",
            "booked_by": None
        }).eq("id", slot_id).execute()

        await interaction.response.send_message(
            "♻️ Slot reset.",
            ephemeral=True
        )

    # ---------------------------
    # LIVE EMBED UPDATE
    # ---------------------------
    async def update_embeds(self, guild):
        msg = self.panel_messages.get(guild.id)
        if not msg:
            return

        res = supabase.table("event_slots").select(
            "slot_no, status"
        ).eq("guild_id", guild.id).execute()

        text = ""
        for row in res.data:
            state = (
                "Available" if row["status"] == "free"
                else "Pending" if row["status"] == "pending"
                else "Booked"
            )
            text += f"🅿️ Slot {row['slot_no']}: *{state}*\n"

        embed = msg.embeds[0]
        embed.description = text
        await msg.edit(embed=embed)


async def setup(bot):
    await bot.add_cog(EventSlots(bot))
