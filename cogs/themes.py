import discord
import aiosqlite
from discord.ext import commands
from discord import app_commands

# =========================================================
# CONFIG
# =========================================================

# Theme registry
# price = coins needed (0 = free)
# tier  = required premium tier (None / bronze / silver / gold)
THEMES = {
    "default": {"price": 0, "tier": None},
    "glow": {"price": 0, "tier": None},
    "dark": {"price": 50, "tier": None},
    "neon": {"price": 100, "tier": None},

    # Premium-only themes
    "bronze_glow": {"price": 0, "tier": "bronze"},
    "silver_neon": {"price": 0, "tier": "silver"},
    "gold_royal": {"price": 0, "tier": "gold"},
}

# Preview styles available (maps to Levels GIF styles)
PREVIEW_STYLES = ["glow", "dark", "neon"]

# =========================================================
# HELPERS
# =========================================================

async def get_active_premium_tier(user_id: int):
    async with aiosqlite.connect("bot.db") as db:
        cur = await db.execute(
            "SELECT tier, expires FROM premium WHERE user_id=?",
            (user_id,)
        )
        row = await cur.fetchone()
        if not row:
            return None
        tier, expires = row
        if expires and expires < int(discord.utils.utcnow().timestamp()):
            return None
        return tier

async def get_user_theme(user_id: int):
    async with aiosqlite.connect("bot.db") as db:
        cur = await db.execute(
            "SELECT theme FROM user_themes WHERE user_id=?",
            (user_id,)
        )
        row = await cur.fetchone()
        return row[0] if row else "default"

async def set_user_theme(user_id: int, theme: str):
    async with aiosqlite.connect("bot.db") as db:
        await db.execute(
            "INSERT OR REPLACE INTO user_themes (user_id, theme) VALUES (?,?)",
            (user_id, theme)
        )
        await db.commit()

# =========================================================
# PREVIEW VIEW (BUTTONS)
# =========================================================

class ThemePreviewView(discord.ui.View):
    def __init__(self, user: discord.Member, theme: str):
        super().__init__(timeout=90)
        self.user = user
        self.theme = theme

    async def interaction_check(self, interaction: discord.Interaction):
        return interaction.user.id == self.user.id

    async def _send_preview(self, interaction: discord.Interaction, style: str):
        # Premium check (theme-tier)
        theme_cfg = THEMES.get(self.theme)
        if not theme_cfg:
            return await interaction.response.send_message(
                "❌ Theme not found.",
                ephemeral=True
            )

        required_tier = theme_cfg["tier"]
        user_tier = await get_active_premium_tier(interaction.user.id)

        if required_tier and user_tier != required_tier:
            return await interaction.response.send_message(
                f"🔒 **{required_tier.title()} Premium** required for this theme.",
                ephemeral=True
            )

        # Import animated GIF generator from levels
        from cogs.levels import generate_animated_rank_card, xp_for_next_level

        # Dummy preview values (safe & fast)
        level = 10
        xp = 250
        max_xp = xp_for_next_level(level)

        gif = generate_animated_rank_card(
            interaction.user,
            level,
            xp,
            max_xp,
            user_tier,     # watermark handled inside generator
            style
        )

        await interaction.response.send_message(
            content=f"🎨 **Preview – {self.theme} / {style}**",
            file=discord.File(gif, f"{self.theme}_{style}.gif"),
            ephemeral=True
        )

    @discord.ui.button(label="✨ Glow", style=discord.ButtonStyle.primary)
    async def glow(self, interaction: discord.Interaction, _):
        await self._send_preview(interaction, "glow")

    @discord.ui.button(label="🌑 Dark", style=discord.ButtonStyle.secondary)
    async def dark(self, interaction: discord.Interaction, _):
        await self._send_preview(interaction, "dark")

    @discord.ui.button(label="⚡ Neon", style=discord.ButtonStyle.success)
    async def neon(self, interaction: discord.Interaction, _):
        await self._send_preview(interaction, "neon")

# =========================================================
# COG
# =========================================================

class Themes(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -----------------------------------------------------
    # /themes — list themes + preview
    # -----------------------------------------------------
    @app_commands.command(name="themes", description="🎨 View & preview rank themes")
    async def themes(self, interaction: discord.Interaction):
        user_tier = await get_active_premium_tier(interaction.user.id)
        active = await get_user_theme(interaction.user.id)

        lines = []
        for name, cfg in THEMES.items():
            lock = ""
            if cfg["tier"]:
                lock = f"🔒 {cfg['tier'].title()}"
            else:
                lock = "Free" if cfg["price"] == 0 else f"{cfg['price']} coins"

            mark = "✅" if name == active else "•"
            lines.append(f"{mark} **{name}** — {lock}")

        embed = discord.Embed(
            title="🎨 Rank Themes",
            description="\n".join(lines),
            color=discord.Color.gold()
        )
        embed.set_footer(text=f"Active theme: {active} | Your tier: {user_tier or 'Free'}")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # -----------------------------------------------------
    # /theme_preview — choose a theme then preview buttons
    # -----------------------------------------------------
    @app_commands.command(name="theme_preview", description="🎞️ Preview a theme (GIF)")
    @app_commands.describe(theme="Theme name")
    async def theme_preview(self, interaction: discord.Interaction, theme: str):
        theme = theme.lower()
        if theme not in THEMES:
            return await interaction.response.send_message(
                "❌ Theme not found.",
                ephemeral=True
            )

        embed = discord.Embed(
            title=f"🎨 Theme Preview: {theme}",
            description="Choose a style below to preview the animated rank card.",
            color=discord.Color.gold()
        )

        await interaction.response.send_message(
            embed=embed,
            view=ThemePreviewView(interaction.user, theme),
            ephemeral=True
        )

    # -----------------------------------------------------
    # /set_theme — apply theme (coins + premium checks)
    # -----------------------------------------------------
    @app_commands.command(name="set_theme", description="🎨 Set your active rank theme")
    @app_commands.describe(theme="Theme name")
    async def set_theme(self, interaction: discord.Interaction, theme: str):
        theme = theme.lower()
        if theme not in THEMES:
            return await interaction.response.send_message(
                "❌ Theme not found.",
                ephemeral=True
            )

        cfg = THEMES[theme]

        # Premium check
        if cfg["tier"]:
            user_tier = await get_active_premium_tier(interaction.user.id)
            if user_tier != cfg["tier"]:
                return await interaction.response.send_message(
                    f"🔒 **{cfg['tier'].title()} Premium** required.",
                    ephemeral=True
                )

        # Coin check
        if cfg["price"] > 0:
            async with aiosqlite.connect("bot.db") as db:
                cur = await db.execute(
                    "SELECT balance FROM coins WHERE user_id=?",
                    (interaction.user.id,)
                )
                row = await cur.fetchone()
                balance = row[0] if row else 0

                if balance < cfg["price"]:
                    return await interaction.response.send_message(
                        "❌ Not enough coins.",
                        ephemeral=True
                    )

                await db.execute(
                    "UPDATE coins SET balance = balance - ? WHERE user_id=?",
                    (cfg["price"], interaction.user.id)
                )
                await db.commit()

        await set_user_theme(interaction.user.id, theme)

        await interaction.response.send_message(
            f"✅ Theme set to **{theme}**",
            ephemeral=True
        )

# =========================================================
# SETUP
# =========================================================

async def setup(bot: commands.Bot):
    await bot.add_cog(Themes(bot))
