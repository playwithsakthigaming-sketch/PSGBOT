import discord
from discord.ext import commands
from discord import app_commands
from gtts import gTTS
from langdetect import detect
import asyncio
import os
import re
import time

TTS_FILE = "auto_tts.mp3"
MAX_WORDS = 10
COOLDOWN = 5


def contains_link(text: str) -> bool:
    return bool(re.search(r"https?://|www\.", text))


def remove_emojis(text: str) -> str:
    text = re.sub(r"<a?:\w+:\d+>", "", text)  # custom emojis
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"
        "\U0001F300-\U0001F5FF"
        "\U0001F680-\U0001F6FF"
        "\U0001F900-\U0001F9FF"
        "\U0001FA00-\U0001FAFF"
        "]+",
        flags=re.UNICODE
    )
    return emoji_pattern.sub("", text).strip()


class AutoTextToSpeech(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.enabled = True
        self.allowed_channel_id = None
        self.queue = asyncio.Queue()
        self.last_used = {}

        bot.loop.create_task(self.audio_worker())

    # ========================
    # ADMIN: SET CHANNEL
    # ========================
    @app_commands.command(name="autotts_channel", description="Set Auto TTS text channel")
    @app_commands.checks.has_permissions(administrator=True)
    async def autotts_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        self.allowed_channel_id = channel.id
        await interaction.response.send_message(
            f"✅ Auto TTS channel set to {channel.mention}",
            ephemeral=True
        )

    # ========================
    # ADMIN: ON/OFF
    # ========================
    @app_commands.command(name="autotts", description="Turn Auto TTS on/off")
    @app_commands.checks.has_permissions(administrator=True)
    async def autotts(self, interaction: discord.Interaction, state: str):
        if state.lower() not in ["on", "off"]:
            return await interaction.response.send_message("Use: on or off", ephemeral=True)

        self.enabled = state.lower() == "on"
        await interaction.response.send_message(f"✅ Auto TTS is now {state.upper()}", ephemeral=True)

    # ========================
    # MESSAGE LISTENER
    # ========================
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):

        if not self.enabled:
            return
        if message.author.bot:
            return
        if not self.allowed_channel_id:
            return
        if message.channel.id != self.allowed_channel_id:
            return
        if not message.author.voice:
            return

        content = message.content.strip()
        if not content:
            return
        if contains_link(content):
            return

        clean_text = remove_emojis(content)
        if not clean_text:
            return

        if len(clean_text.split()) > MAX_WORDS:
            return

        # cooldown
        now = time.time()
        last = self.last_used.get(message.author.id, 0)
        if now - last < COOLDOWN:
            return
        self.last_used[message.author.id] = now

        voice_channel = message.author.voice.channel

        try:
            lang = detect(clean_text)
        except:
            lang = "en"

        if lang not in ["ta", "en", "hi"]:
            lang = "en"

        await self.queue.put((message.guild.id, voice_channel.id, clean_text, lang))

    # ========================
    # AUDIO WORKER
    # ========================
    async def audio_worker(self):
        await self.bot.wait_until_ready()

        while True:
            guild_id, channel_id, text, lang = await self.queue.get()

            guild = self.bot.get_guild(guild_id)
            if not guild:
                self.queue.task_done()
                continue

            voice_channel = guild.get_channel(channel_id)
            if not voice_channel:
                self.queue.task_done()
                continue

            try:
                if guild.voice_client is None:
                    vc = await voice_channel.connect()
                else:
                    vc = guild.voice_client
                    if vc.channel != voice_channel:
                        await vc.move_to(voice_channel)

                tts = gTTS(text=text, lang=lang)
                tts.save(TTS_FILE)

                vc.play(discord.FFmpegPCMAudio(TTS_FILE))

                while vc.is_playing():
                    await asyncio.sleep(1)

            except Exception as e:
                print("TTS Error:", e)

            finally:
                if os.path.exists(TTS_FILE):
                    os.remove(TTS_FILE)

            self.queue.task_done()


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoTextToSpeech(bot))
