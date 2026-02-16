import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import os
import re
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
STAFF_ROLE_ID = int(os.getenv("STAFF_ROLE_ID"))

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}


# ===============================
# FETCH TRUCKERSMP EVENT TITLE
# ===============================
async def fetch_event_title(event_input: str):
    match = re.search(r"\d+", event_input)
    if not match:
        return "TruckersMP Event"

    event_id = match.group()
    url = f"https://api.truckersmp.com/v2/events/{event_id}"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                return "TruckersMP Event"
            data = await resp.json()
            return data["response"]["name"]


# ===============================
# BUILD SLOT EMBED
# ===============================
async def build_slot_embed(event_db_id):
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{SUPABASE_URL}/rest/v1/event_slots"
            f"?event_id=eq.{event_db_id}"
            f"&select=slot_number,vtc_name,confirmed"
            f"&order=slot_number.asc",
            headers=HEADERS
        ) as resp:
            slots = await resp.json()

    description = ""
    if not slots:
        description = "No bookings yet."
    else:
        for s in slots:
            status = "🔴 Confirmed" if s["confirmed"] else "🟡 Pending"
            description += (
                f"**Slot {s['slot_number']}** — "
                f"{s['vtc_name']} ({status})\n"
            )

    embed = discord.Embed(
        title="📋 Slot List",
        description=description,
        color=discord.Color.orange()
    )
    return embed


# ===============================
# STAFF CONFIRM VIEW
# ===============================
class StaffConfirmView(discord.ui.View):
    def __init__(self, bot, event_db_id, slot_number):
        super().__init__(timeout=None)
        self.bot = bot
        self.event_db_id = event_db_id
        self.slot_number = slot_number

    @discord.ui.button(label="Confirm Slot", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button):

        if STAFF_ROLE_ID not in [r.id for r in interaction.user.roles]:
            return await interaction.response.send_message(
                "❌ Staff only.",
                ephemeral=True
            )

        async with aiohttp.ClientSession() as session:
            await session.patch(
                f"{SUPABASE_URL}/rest/v1/event_slots"
                f"?event_id=eq.{self.event_db_id}"
                f"&slot_number=eq.{self.slot_number}",
                headers=HEADERS,
                json={"confirmed": True}
            )

            async with session.get(
                f"{SUPABASE_URL}/rest/v1/event_slots"
                f"?event_id=eq.{self.event_db_id}"
                f"&slot_number=eq.{self.slot_number}"
                f"&select=user_id,slot_title,slot_image",
                headers=HEADERS
            ) as resp:
                data = await resp.json()

        # Send DM
        if data:
            user = self.bot.get_user(data[0]["user_id"])
            if user:
                embed = discord.Embed(
                    title="✅ Slot Confirmed",
                    color=discord.Color.red()
                )
                embed.add_field(
                    name="Slot",
                    value=str(self.slot_number)
                )
                embed.add_field(
                    name="Type",
                    value=data[0]["slot_title"]
                )
                if data[0]["slot_image"]:
                    embed.set_image(url=data[0]["slot_image"])

                try:
                    await user.send(embed=embed)
                except:
                    pass

        button.disabled = True
        await interaction.response.edit_message(
            content=f"🔴 Slot {self.slot_number} confirmed.",
            view=self
        )


# ===============================
# BOOKING MODAL
# ===============================
class BookingModal(discord.ui.Modal, title="Slot Booking"):
    def __init__(self, bot, event_db_id):
        super().__init__()
        self.bot = bot
        self.event_db_id = event_db_id

        self.vtc = discord.ui.TextInput(
            label="VTC Name",
            placeholder="Enter your VTC name",
            required=True
        )
        self.add_item(self.vtc)

    async def on_submit(self, interaction: discord.Interaction):
        view = SlotSelectView(self.bot, self.event_db_id, self.vtc.value)
        await interaction.response.send_message(
            "Select slot:",
            view=view,
            ephemeral=True
        )


# ===============================
# SLOT SELECT
# ===============================
class SlotSelect(discord.ui.Select):
    def __init__(self, bot, event_db_id, vtc_name):
        options = [
            discord.SelectOption(label=f"Slot {i}", value=str(i))
            for i in range(1, 6)
        ]
        super().__init__(placeholder="Choose slot", options=options)
        self.bot = bot
        self.event_db_id = event_db_id
        self.vtc_name = vtc_name

    async def callback(self, interaction: discord.Interaction):
        slot = int(self.values[0])

        payload = {
            "event_id": self.event_db_id,
            "slot_number": slot,
            "slot_title": "Public",
            "slot_image": "",
            "vtc_name": self.vtc_name,
            "user_id": interaction.user.id,
            "username": str(interaction.user),
            "confirmed": False
        }

        async with aiohttp.ClientSession() as session:
            await session.post(
                f"{SUPABASE_URL}/rest/v1/event_slots",
                headers=HEADERS,
                json=payload
            )

        view = StaffConfirmView(self.bot, self.event_db_id, slot)
        await interaction.response.send_message(
            f"🟡 Slot {slot} requested.",
            view=view,
            ephemeral=True
        )


class SlotSelectView(discord.ui.View):
    def __init__(self, bot, event_db_id, vtc_name):
        super().__init__(timeout=300)
        self.add_item(SlotSelect(bot, event_db_id, vtc_name))


# ===============================
# STAFF DASHBOARD
# ===============================
class StaffDashboard(discord.ui.View):
    def __init__(self, event_db_id):
        super().__init__(timeout=None)
        self.event_db_id = event_db_id

    async def interaction_check(self, interaction: discord.Interaction):
        if STAFF_ROLE_ID not in [r.id for r in interaction.user.roles]:
            await interaction.response.send_message(
                "❌ Staff only.",
                ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="View Slots", style=discord.ButtonStyle.primary)
    async def view_slots(self, interaction: discord.Interaction, button):
        embed = await build_slot_embed(self.event_db_id)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Reset All", style=discord.ButtonStyle.danger)
    async def reset_all(self, interaction: discord.Interaction, button):
        async with aiohttp.ClientSession() as session:
            await session.delete(
                f"{SUPABASE_URL}/rest/v1/event_slots"
                f"?event_id=eq.{self.event_db_id}",
                headers=HEADERS
            )
        await interaction.response.send_message(
            "All slots reset.",
            ephemeral=True
        )


# ===============================
# MAIN COG
# ===============================
class EventSlots(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="eventslot", description="Create event slot system")
    async def eventslot(
        self,
        interaction: discord.Interaction,
        event_id_or_url: str,
        date: str,
        time: str,
        route_details: str,
        route_image: str
    ):
        await interaction.response.defer()

        title = await fetch_event_title(event_id_or_url)

        payload = {
            "guild_id": interaction.guild_id,
            "event_id": event_id_or_url,
            "title": title,
            "date": date,
            "time": time,
            "route_details": route_details,
            "route_image": route_image
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{SUPABASE_URL}/rest/v1/events",
                headers={**HEADERS, "Prefer": "return=representation"},
                json=payload
            ) as resp:
                data = await resp.json()
                event_db_id = data[0]["id"]

        embed = discord.Embed(
            title=title,
            description=event_id_or_url,
            color=discord.Color.orange()
        )
        embed.add_field(name="Date", value=date)
        embed.add_field(name="Time", value=time)
        embed.add_field(name="Route", value=route_details)
        embed.set_image(url=route_image)

        view = discord.ui.View()
        button = discord.ui.Button(label="Book Slot")

        async def callback(i: discord.Interaction):
            await i.response.send_modal(
                BookingModal(self.bot, event_db_id)
            )

        button.callback = callback
        view.add_item(button)

        msg = await interaction.followup.send(embed=embed, view=view)

        # Save message id
        async with aiohttp.ClientSession() as session:
            await session.patch(
                f"{SUPABASE_URL}/rest/v1/events"
                f"?id=eq.{event_db_id}",
                headers=HEADERS,
                json={"message_id": msg.id}
            )

    @app_commands.command(name="staffpanel")
    async def staffpanel(self, interaction: discord.Interaction, event_id: int):
        view = StaffDashboard(event_id)
        await interaction.response.send_message(
            "Staff Panel",
            view=view,
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(EventSlots(bot))
