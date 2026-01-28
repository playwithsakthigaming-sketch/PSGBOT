import discord
from discord.ext import commands
from discord import app_commands
import math

PAGE_SIZE = 6

# ================= UTIL FUNCTIONS =================

def is_admin(interaction: discord.Interaction):
    return interaction.user.guild_permissions.administrator


def get_all_commands(bot: commands.Bot):
    categories = {}
    for cmd in bot.tree.get_commands():
        category = cmd.extras.get("category", "General")
        categories.setdefault(category, []).append(cmd)
    return categories


def get_admin_commands(bot: commands.Bot):
    categories = {}
    for cmd in bot.tree.get_commands():
        if cmd.default_permissions:
            category = cmd.extras.get("category", "Admin")
            categories.setdefault(category, []).append(cmd)
    return categories


def filter_user_commands(cmds, interaction):
    filtered = []
    for cmd in cmds:
        if cmd.default_permissions and not interaction.user.guild_permissions.administrator:
            continue
        filtered.append(cmd)
    return filtered


# ================= EMBEDS =================

def home_embed():
    embed = discord.Embed(
        title="🤖 PSG FAMILY BOT - Help Menu",
        description=(
            "Select a category from the dropdown below.\n\n"
            "✨ Features:\n"
            "• Dynamic command list\n"
            "• Role-based visibility\n"
            "• Multi-page UI\n"
            "• Search support\n\n"
            "🔍 Use `/help_search <command>` to find commands."
        ),
        color=discord.Color.gold()
    )
    embed.set_footer(text="PSG Family Bot • Interactive Help")
    return embed


def admin_home_embed():
    embed = discord.Embed(
        title="🛡️ Admin Help Panel",
        description=(
            "This panel shows **Admin-only commands**.\n\n"
            "Select a category from the dropdown.\n"
            "⚠️ Visible only to administrators."
        ),
        color=discord.Color.red()
    )
    embed.set_footer(text="PSG Family Bot • Admin Help")
    return embed


def category_embed(category, commands_list, page):
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    sliced = commands_list[start:end]

    embed = discord.Embed(
        title=f"📂 {category} Commands",
        color=discord.Color.gold()
    )

    for cmd in sliced:
        embed.add_field(
            name=f"/{cmd.name}",
            value=cmd.description or "No description",
            inline=False
        )

    total_pages = max(1, math.ceil(len(commands_list) / PAGE_SIZE))
    embed.set_footer(text=f"Page {page+1}/{total_pages}")
    return embed


# ================= VIEWS =================

class HelpView(discord.ui.View):
    def __init__(self, bot, interaction, category=None, page=0):
        super().__init__(timeout=180)
        self.bot = bot
        self.interaction = interaction
        self.category = category
        self.page = page
        self.categories = get_all_commands(bot)

        self.add_item(HelpSelect(self))

        if category:
            self.add_item(PrevButton(self))
            self.add_item(NextButton(self))

        self.add_item(HomeButton(self))


class AdminHelpView(discord.ui.View):
    def __init__(self, bot, interaction, category=None, page=0):
        super().__init__(timeout=180)
        self.bot = bot
        self.interaction = interaction
        self.category = category
        self.page = page
        self.categories = get_admin_commands(bot)

        self.add_item(AdminHelpSelect(self))

        if category:
            self.add_item(PrevButton(self))
            self.add_item(NextButton(self))

        self.add_item(HomeButtonAdmin(self))


# ================= SELECT MENUS =================

class HelpSelect(discord.ui.Select):
    def __init__(self, view: HelpView):
        options = [
            discord.SelectOption(label=cat, emoji="📁")
            for cat in view.categories.keys()
        ]
        super().__init__(
            placeholder="Select a command category",
            options=options,
            custom_id="help_select"
        )
        self.view_ref = view

    async def callback(self, interaction: discord.Interaction):
        category = self.values[0]
        cmds = filter_user_commands(self.view_ref.categories[category], interaction)

        embed = category_embed(category, cmds, 0)

        await interaction.response.edit_message(
            embed=embed,
            view=HelpView(self.view_ref.bot, interaction, category, 0)
        )


class AdminHelpSelect(discord.ui.Select):
    def __init__(self, view: AdminHelpView):
        options = [
            discord.SelectOption(label=cat, emoji="🛡️")
            for cat in view.categories.keys()
        ]
        super().__init__(
            placeholder="Select admin command category",
            options=options,
            custom_id="admin_help_select"
        )
        self.view_ref = view

    async def callback(self, interaction: discord.Interaction):
        category = self.values[0]
        cmds = self.view_ref.categories[category]

        embed = category_embed(category, cmds, 0)

        await interaction.response.edit_message(
            embed=embed,
            view=AdminHelpView(self.view_ref.bot, interaction, category, 0)
        )


# ================= BUTTONS =================

class NextButton(discord.ui.Button):
    def __init__(self, view):
        super().__init__(label="➡ Next", style=discord.ButtonStyle.primary)
        self.view_ref = view

    async def callback(self, interaction: discord.Interaction):
        cmds = self.view_ref.categories[self.view_ref.category]
        cmds = filter_user_commands(cmds, interaction)

        total_pages = math.ceil(len(cmds) / PAGE_SIZE)
        if self.view_ref.page + 1 >= total_pages:
            return await interaction.response.send_message("❌ Last page.", ephemeral=True)

        new_page = self.view_ref.page + 1
        embed = category_embed(self.view_ref.category, cmds, new_page)

        await interaction.response.edit_message(
            embed=embed,
            view=self.view_ref.__class__(self.view_ref.bot, interaction, self.view_ref.category, new_page)
        )


class PrevButton(discord.ui.Button):
    def __init__(self, view):
        super().__init__(label="⬅ Prev", style=discord.ButtonStyle.primary)
        self.view_ref = view

    async def callback(self, interaction: discord.Interaction):
        if self.view_ref.page == 0:
            return await interaction.response.send_message("❌ First page.", ephemeral=True)

        cmds = self.view_ref.categories[self.view_ref.category]
        cmds = filter_user_commands(cmds, interaction)

        new_page = self.view_ref.page - 1
        embed = category_embed(self.view_ref.category, cmds, new_page)

        await interaction.response.edit_message(
            embed=embed,
            view=self.view_ref.__class__(self.view_ref.bot, interaction, self.view_ref.category, new_page)
        )


class HomeButton(discord.ui.Button):
    def __init__(self, view):
        super().__init__(label="🏠 Home", style=discord.ButtonStyle.secondary)
        self.view_ref = view

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            embed=home_embed(),
            view=HelpView(self.view_ref.bot, interaction)
        )


class HomeButtonAdmin(discord.ui.Button):
    def __init__(self, view):
        super().__init__(label="🏠 Admin Home", style=discord.ButtonStyle.danger)
        self.view_ref = view

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            embed=admin_home_embed(),
            view=AdminHelpView(self.view_ref.bot, interaction)
        )


# ================= COG =================

class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # -------- USER HELP --------
    @app_commands.command(name="help", description="Show interactive help menu")
    async def help(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            embed=home_embed(),
            view=HelpView(self.bot, interaction),
            ephemeral=True
        )

    # -------- ADMIN HELP --------
    @app_commands.command(name="help_admin", description="Show admin help panel")
    @app_commands.checks.has_permissions(administrator=True)
    async def help_admin(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            embed=admin_home_embed(),
            view=AdminHelpView(self.bot, interaction),
            ephemeral=True
        )

    # -------- SEARCH --------
    @app_commands.command(name="help_search", description="Search for a command")
    async def help_search(self, interaction: discord.Interaction, query: str):
        results = []
        for cmd in self.bot.tree.get_commands():
            if query.lower() in cmd.name.lower():
                if cmd.default_permissions and not interaction.user.guild_permissions.administrator:
                    continue
                results.append(cmd)

        if not results:
            return await interaction.response.send_message("❌ No command found.", ephemeral=True)

        embed = discord.Embed(title="🔍 Search Results", color=discord.Color.gold())

        for cmd in results[:10]:
            embed.add_field(
                name=f"/{cmd.name}",
                value=cmd.description or "No description",
                inline=False
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)


# ================= SETUP =================

async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))
