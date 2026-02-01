import discord
import os
import shutil
import traceback
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime

DB_FILE = "bot.db"
BACKUP_FOLDER = "balance_backups"
MAX_BACKUPS = 2

ADMIN_ALERT_USER_ID = 671669229182779392


# ==========================
# CONFIRM RESTORE VIEW
# ==========================
class RestoreConfirmView(discord.ui.View):
    def __init__(self, filename: str):
        super().__init__(timeout=60)
        self.filename = filename

    @discord.ui.button(label="✅ Confirm Restore", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, _):
        try:
            shutil.copy(
                os.path.join(BACKUP_FOLDER, self.filename),
                DB_FILE
            )
            await interaction.response.edit_message(
                content=f"♻ **Database restored from `{self.filename}`**\n⚠ Restart the bot now!",
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


# ==========================
# BACKUP SELECT MENU
# ==========================
class BackupSelect(discord.ui.Select):
    def __init__(self, backups):
        options = [
            discord.SelectOption(label=f)
            for f in backups
        ]

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


# ==========================
# MAIN COG
# ==========================
class AutoBalanceBackup(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        os.makedirs(BACKUP_FOLDER, exist_ok=True)
        self.auto_backup.start()

    # ==========================
    # AUTO BACKUP TASK
    # ==========================
    @tasks.loop(minutes=30)  # change time if needed
    async def auto_backup(self):
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            backup_name = f"balance_backup_{timestamp}.db"
            backup_path = os.path.join(BACKUP_FOLDER, backup_name)

            shutil.copy(DB_FILE, backup_path)
            print(f"✅ Backup created: {backup_name}")

            self.cleanup_old_backups()

        except Exception as e:
            await self.alert_admin(e)

    # ==========================
    # CLEANUP (KEEP ONLY 2)
    # ==========================
    def cleanup_old_backups(self):
        files = sorted(os.listdir(BACKUP_FOLDER), reverse=True)

        if len(files) > MAX_BACKUPS:
            for old_file in files[MAX_BACKUPS:]:
                os.remove(os.path.join(BACKUP_FOLDER, old_file))
                print(f"🗑 Deleted old backup: {old_file}")

    # ==========================
    # RESTORE COMMAND
    # ==========================
    @app_commands.command(
        name="restore_backup",
        description="♻ Restore database from last balance backups"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def restore_backup_cmd(self, interaction: discord.Interaction):
        files = sorted(os.listdir(BACKUP_FOLDER), reverse=True)

        if not files:
            return await interaction.response.send_message(
                "❌ No backups found.",
                ephemeral=True
            )

        await interaction.response.send_message(
            "📂 Select a backup file to restore:",
            view=BackupSelectView(files[:2]),  # only show last 2
            ephemeral=True
        )

    # ==========================
    # ADMIN ALERT
    # ==========================
    async def alert_admin(self, error: Exception):
        try:
            admin = await self.bot.fetch_user(ADMIN_ALERT_USER_ID)
            await admin.send(
                "🚨 **AUTO BALANCE BACKUP FAILED**\n"
                f"```{traceback.format_exc()}```"
            )
        except:
            pass

    # ==========================
    # START TASK
    # ==========================
    @commands.Cog.listener()
    async def on_ready(self):
        if not self.auto_backup.is_running():
            self.auto_backup.start()
        print("✅ Auto balance backup system running")


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoBalanceBackup(bot))
