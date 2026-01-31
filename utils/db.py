import aiosqlite

DB_NAME = "bot.db"

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:

        # ================= SQLITE SAFETY =================
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("PRAGMA synchronous=NORMAL;")
        await db.execute("PRAGMA foreign_keys=ON;")

        # ================= COINS =================
        await db.execute("""
        CREATE TABLE IF NOT EXISTS coins (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER DEFAULT 0
        )
        """)

        # ================= PREMIUM =================
        await db.execute("""
        CREATE TABLE IF NOT EXISTS premium (
            user_id INTEGER PRIMARY KEY,
            tier TEXT,
            expires INTEGER
        )
        """)

        # ================= PAYMENTS / INVOICES =================
        await db.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            invoice_id TEXT PRIMARY KEY,
            user_id INTEGER,
            rupees INTEGER,
            coins INTEGER,
            timestamp INTEGER
        )
        """)

        # ================= LEVELS =================
        await db.execute("""
        CREATE TABLE IF NOT EXISTS levels (
            user_id INTEGER,
            guild_id INTEGER,
            xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            PRIMARY KEY (user_id, guild_id)
        )
        """)

        # ================= THEMES =================
        await db.execute("""
        CREATE TABLE IF NOT EXISTS user_themes (
            user_id INTEGER PRIMARY KEY,
            theme TEXT DEFAULT 'default'
        )
        """)

        # ================= GUILD SETTINGS =================
        await db.execute("""
        CREATE TABLE IF NOT EXISTS guild_settings (
            guild_id INTEGER PRIMARY KEY,
            welcome_channel INTEGER,
            welcome_role INTEGER,
            welcome_message TEXT
        )
        """)

        # ================= TICKETS =================
        await db.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            channel_id INTEGER PRIMARY KEY,
            user_id INTEGER,
            claimed_by INTEGER,
            category TEXT,
            created_at INTEGER
        )
        """)

        # ================= TICKET COOLDOWNS =================
        await db.execute("""
        CREATE TABLE IF NOT EXISTS ticket_cooldowns (
            user_id INTEGER PRIMARY KEY,
            last_created INTEGER
        )
        """)

        # ================= TRANSCRIPTS =================
        await db.execute("""
        CREATE TABLE IF NOT EXISTS ticket_transcripts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER,
            author_id INTEGER,
            message TEXT,
            timestamp INTEGER
        )
        """)

        # ================= WARNINGS =================
        await db.execute("""
        CREATE TABLE IF NOT EXISTS warnings (
            user_id INTEGER,
            guild_id INTEGER,
            count INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, guild_id)
        )
        """)

        # ================= YOUTUBE ALERTS =================
        await db.execute("""
        CREATE TABLE IF NOT EXISTS youtube_alerts (
            guild_id INTEGER,
            youtube_channel TEXT,
            discord_channel INTEGER,
            role_ping INTEGER,
            message TEXT,
            last_video TEXT,
            PRIMARY KEY (guild_id, youtube_channel)
        )
        """)

        # ================= COUPONS =================
        await db.execute("""
        CREATE TABLE IF NOT EXISTS coupons (
            code TEXT PRIMARY KEY,
            type TEXT,
            value INTEGER,
            max_uses INTEGER,
            used INTEGER DEFAULT 0,
            expires INTEGER
        )
        """)

        # ================= SHOP CATEGORIES =================
        await db.execute("""
        CREATE TABLE IF NOT EXISTS shop_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE
        )
        """)

        # ================= SHOP ITEMS =================
        await db.execute("""
        CREATE TABLE IF NOT EXISTS shop_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            price INTEGER,
            stock INTEGER,
            image_url TEXT,
            category_id INTEGER
        )
        """)

        # ================= USER LINKS (AUTO GENERATED) =================
        await db.execute("""
        CREATE TABLE IF NOT EXISTS user_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            item_id INTEGER,
            link TEXT,
            expires INTEGER,
            used INTEGER DEFAULT 0
        )
        """)

        # ================= ORDERS (UPDATED WITH ITEM NAME) =================
        await db.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            item_name TEXT,
            total INTEGER,
            timestamp INTEGER
        )
        """)

        await db.commit()
        print("✅ Database checked & updated (shop + user links system ready)")
