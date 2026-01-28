import discord
import aiosqlite
import time
from discord.ext import commands, tasks
from discord import app_commands

# =========================================================
# CONFIG
# =========================================================

CHAT_COIN_COOLDOWN = 30        # seconds
CHAT_COINS_EARNED = 2

VC_COINS_EARNED = 5            # coins per interval
VC_INTERVAL_MINUTES = 5        # every 5 minutes
VC_AFK_MINUTES = 20            # AFK detection

# =========================================================
# ECONOMY COG
# =========================================================

class Economy(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.chat_cooldown = {}
        self.vc_join_time = {}
        self.vc_coin_loop.start()

    # -----------------------------------------------------
    # CHAT COIN EARNING
    # -----------------------------------------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        user_id = message.author.id
        now = time.time()

        last = self.chat_cooldown.get(user_id, 0)
        if now - last < CHAT_COIN_COOLDOWN:
            return

        self.chat_cooldown[user_id] = now

        async with aiosqlite.connect("bot.db") as db:
            await db.execute(
                "INSERT OR IGNORE INTO coins (user_id, balance) VALUES (?,0)",
                (user_id,)
            )
            await db.execute(
                "UPDATE coins SET balance = balance + ? WHERE user_id=?",
                (CHAT_COINS_EARNED, user_id)
            )
            await db.commit()

    # -----------------------------------------------------
    # VOICE JOIN / LEAVE TRACK
    # -----------------------------------------------------
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return

        # Joined VC
        if after.channel and not before.channel:
            self.vc_join_time[member.id] = time.time()

        # Left VC
        if before.channel and not after.channel:
            self.vc_join_time.pop(member.id, None)

    # -----------------------------------------------------
    # VC COIN LOOP
    # -----------------------------------------------------
    @tasks.loop(minutes=VC_INTERVAL_MINUTES)
    async def vc_coin_loop(self):
        now = time.time()

        for guild in self.bot.guilds:
            for channel in guild.voice_channels:
                for member in channel.members:
                    if member.bot:
                        continue

                    # AFK / muted protection
                    if member.voice.self_mute or member.voice.afk:
                        continue

                    joined_at = self.vc_join_time.get(member.id)
                    if not joined_at:
                        continue

                    # Must stay minimum time
                    if now - joined_at < VC_AFK_MINUTES * 60:
                        continue

                    async with aiosqlite.connect("bot.db") as db:
                        await db.execute(
                            "INSERT OR IGNORE INTO coins (user_id, balance) VALUES (?,0)",
                            (member.id,)
                        )
                        await db.execute(
                            "UPDATE coins SET balance = balance + ? WHERE user_id=?",
                            (VC_COINS_EARNED, member.id)
                        )
                        await db.commit()

    # -----------------------------------------------------
    # /balance COMMAND
    # -----------------------------------------------------
    @app_commands.command(name="balance", description="🪙 Check your coin balance")
    async def balance(self, interaction: discord.Interaction):
        async with aiosqlite.connect("bot.db") as db:
            cur = await db.execute(
                "SELECT balance FROM coins WHERE user_id=?",
                (interaction.user.id,)
            )
            row = await cur.fetchone()

        balance = row[0] if row else 0

        embed = discord.Embed(
            title="🪙 PSG Coin Balance",
            description=f"**{balance} PSG Coins**",
            color=discord.Color.gold()
        )
        embed.set_footer(text=interaction.user.name)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # -----------------------------------------------------
    # ADMIN: ADD COINS
    # -----------------------------------------------------
    @app_commands.command(name="add_coins", description="➕ Add coins to a user")
    @app_commands.checks.has_permissions(administrator=True)
    async def add_coins(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        amount: int
    ):
        if amount <= 0:
            return await interaction.response.send_message(
                "❌ Amount must be positive.",
                ephemeral=True
            )

        async with aiosqlite.connect("bot.db") as db:
            await db.execute(
                "INSERT OR IGNORE INTO coins (user_id, balance) VALUES (?,0)",
                (member.id,)
            )
            await db.execute(
                "UPDATE coins SET balance = balance + ? WHERE user_id=?",
                (amount, member.id)
            )
            await db.commit()

        await interaction.response.send_message(
            f"✅ Added **{amount} coins** to {member.mention}",
            ephemeral=True
        )

    # -----------------------------------------------------
    # ADMIN: REMOVE COINS
    # -----------------------------------------------------
    @app_commands.command(name="remove_coins", description="➖ Remove coins from a user")
    @app_commands.checks.has_permissions(administrator=True)
    async def remove_coins(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        amount: int
    ):
        if amount <= 0:
            return await interaction.response.send_message(
                "❌ Amount must be positive.",
                ephemeral=True
            )

        async with aiosqlite.connect("bot.db") as db:
            cur = await db.execute(
                "SELECT balance FROM coins WHERE user_id=?",
                (member.id,)
            )
            row = await cur.fetchone()
            balance = row[0] if row else 0

            if balance < amount:
                return await interaction.response.send_message(
                    "❌ User does not have enough coins.",
                    ephemeral=True
                )

            await db.execute(
                "UPDATE coins SET balance = balance - ? WHERE user_id=?",
                (amount, member.id)
            )
            await db.commit()

        await interaction.response.send_message(
            f"✅ Removed **{amount} coins** from {member.mention}",
            ephemeral=True
        )

# =========================================================
# SETUP
# =========================================================

async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))
