import discord
from discord.ext import commands, tasks
import asyncio
import os
from dotenv import load_dotenv
import threading

from utils.db import init_db
from utils.backup import backup_db

# ================================
# LOAD ENV
# ================================
print("▶ Loading env")
load_dotenv()
print("▶ Env loaded")

# ================================
# DISCORD INTENTS
# ================================
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.voice_states = True

# ================================
# COG LIST
# ================================
COGS = [
    "cogs.welcome",
    "cogs.tickets",
    "cogs.economy",
    "cogs.levels",
    "cogs.status",
    "cogs.premium",
    "cogs.payment",
    "cogs.coin_shop",
    "cogs.announce",
    "cogs.help",
    "cogs.moderation",
    "cogs.link_storage",
    "cogs.birthday",
    "cogs.coupons",
    "cogs.backup",
    "cogs.admin",
    "cogs.auto_tts",
    "cogs.truckersmp_events",
    "cogs.vtc_auto_events",
    "cogs.shop",
    "cogs.youtube"
]

# ================================
# BOT CLASS
# ================================
class MyBot(commands.Bot):
    async def setup_hook(self):
        await init_db()
        print("✅ Database initialized")

        for cog in COGS:
            try:
                await self.load_extension(cog)
                print(f"✅ Loaded {cog}")
            except Exception as e:
                print(f"❌ Failed to load {cog}: {e}")

        await self.tree.sync()
        print("✅ Slash commands synced")


bot = MyBot(command_prefix="!", intents=intents)

# ================================
# BACKUP TASK
# ================================
@tasks.loop(hours=6)
async def db_backup_loop():
    backup_db()
    print("💾 Database backup created")

@db_backup_loop.before_loop
async def before_backup():
    await bot.wait_until_ready()

# ================================
# BOT EVENTS
# ================================
@bot.event
async def on_ready():
    print(f"🤖 Logged in as {bot.user}")

    if not db_backup_loop.is_running():
        db_backup_loop.start()

    print("✅ Bot fully ready")


# =========================================================
# FLASK FILE SERVER (for Railway)
# =========================================================
from flask import Flask, request, send_from_directory, jsonify, abort
import uuid

app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
BASE_URL = "https://files.psgfamily.online"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


@app.route("/")
def home():
    return "File server running", 200


@app.route("/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]

    if file.filename == "":
        return jsonify({"error": "Empty filename"}), 400

    ext = file.filename.split(".")[-1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    path = os.path.join(UPLOAD_FOLDER, filename)

    file.save(path)

    return jsonify({
        "url": f"{BASE_URL}/{filename}"
    })


@app.route("/<filename>")
def serve_file(filename):
    path = os.path.join(UPLOAD_FOLDER, filename)
    if not os.path.exists(path):
        abort(404)
    return send_from_directory(UPLOAD_FOLDER, filename)


def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)


# =========================================================
# MAIN START
# =========================================================
async def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("❌ DISCORD_TOKEN missing in .env")

    # Start Flask server in background thread
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()

    await bot.start(token)


asyncio.run(main())
