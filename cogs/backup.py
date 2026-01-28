import discord
import traceback
from discord.ext import commands
from discord import app_commands
from utils.backup import (
    backup_db,
    restore_backup,
    list_backups_with_size
)

# 🔴 CHANGE THIS TO YOUR DISCORD USER ID
ADMIN_ALERT_USER_ID = 671669229182779392

# =================================================
# CONFIRM RESTORE VIEW
# =================================================
class RestoreConfirmView(discord.ui.View):
    def __init__(self, filename: str):
        super().__init__(timeout=60)
        self.filename = filename

    @discord.ui.button(label="✅ Confirm Restore", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, _):
        try:
            restore_backup(self.filename)
            await interaction.response.edit_message(
                content=(
                    f"♻ **Database restored from `{self.filename}`**\n"
                    "⚠ **Restart the bot now!**"
                ),
                view=None
            )
        except Exception as e:
            await interaction.response.edit_message(
                content=f"❌ Restore failed:\n```{e}```",
                view=None
            )

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _):
        await interaction.response.edit_message(
            content="❌ Restore cancelled.",
            view=None
        )

# =================================================
# BACKUP DROPDOWN
# =================================================
class BackupSelect(discord.ui.Select):
    def __init__(self, backups):
        options = []
        for name, size in backups[:25]:
            options.append(
                discord.SelectOption(
                    label=name,
                    description=f"Size: {size} MB"
                )
            )

        super().__init__(
            placeholder="Select a backup file to restore",
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        filename = self.values[0]
        await interaction.response.send_message(
            content=f"⚠ **Confirm restore from `{filename}`**",
            view=RestoreConfirmView(filename),
            ephemeral=True
        )

class BackupSelectView(discord.ui.View):
    def __init__(self, backups):
        super().__init__(timeout=60)
        self.add_item(BackupSelect(backups))

# =================================================
# BACKUP COG
# =================================================
class Backup(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -----------------------------
    # /backup_now
    # -----------------------------
    @app_commands.command(
        name="backup_now",
        description="💾 Create database backup now"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def backup_now(self, interaction: discord.Interaction):
        try:
            path = backup_db()
            await interaction.response.send_message(
                f"✅ Backup created successfully:\n`{path}`",
                ephemeral=True
            )
        except Exception as e:
            await self.alert_admin(e)
            await interaction.response.send_message(
                "❌ Backup failed. Admin has been alerted.",
                ephemeral=True
            )

    # -----------------------------
    # /restore_backup
    # -----------------------------
    @app_commands.command(
        name="restore_backup",
        description="♻ Restore database from backup"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def restore_backup_cmd(self, interaction: discord.Interaction):
        backups = list_backups_with_size()
        if not backups:
            return await interaction.response.send_message(
                "❌ No backups found.",
                ephemeral=True
            )

        await interaction.response.send_message(
            "📂 **Select a backup file to restore**",
            view=BackupSelectView(backups),
            ephemeral=True
        )

    # -----------------------------
    # ADMIN ALERT (DM)
    # -----------------------------
    async def alert_admin(self, error: Exception):
        try:
            admin = await self.bot.fetch_user(ADMIN_ALERT_USER_ID)
            await admin.send(
                "🚨 **DATABASE BACKUP FAILED**\n"
                f"```{traceback.format_exc()}```"
            )
        except:
            pass

async def setup(bot: commands.Bot):
    await bot.add_cog(Backup(bot))
