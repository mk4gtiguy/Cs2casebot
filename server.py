# ============================================================
# SERVER.PY — FastAPI Web Server Entrypoint
# CS2CaseBot | Mounts all routers, serves static files
# Run with: uvicorn server:app --host 0.0.0.0 --port 8000
# ============================================================

import os
import asyncio
import secrets
import logging
import random
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, List

from fastapi import (
    FastAPI, Request, Response, HTTPException,
    Depends, WebSocket, WebSocketDisconnect
)
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import httpx

# ─── Load env ────────────────────────────────────────────────
if os.path.exists('.env'):
    load_dotenv()

DATABASE_URL          = os.getenv('DATABASE_URL', '')
DISCORD_CLIENT_ID     = os.getenv('DISCORD_CLIENT_ID', '')
DISCORD_CLIENT_SECRET = os.getenv('DISCORD_CLIENT_SECRET', '')
DISCORD_REDIRECT_URI  = os.getenv('DISCORD_REDIRECT_URI', 'https://cs2casebot.xyz/auth/discord/callback')

# ─── Load admin / moderator IDs from env ─────────────────────
_admin_env = os.getenv('ADMIN_USER_IDS', '')
_mod_env   = os.getenv('MODERATOR_USER_IDS', '')
shared_import_done = False   # populated after shared import below
STRIPE_SECRET_KEY     = os.getenv('STRIPE_SECRET_KEY', '')
STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET', '')
KO_FI_URL             = "https://ko-fi.com/mk4gtiguy"
DASHBOARD_URL         = "https://cs2casebot.xyz/"

# ─── Shared imports ──────────────────────────────────────────
import shared
from shared import (
    logger, sessions, get_user_id_from_session, require_auth,
    require_admin, require_admin_or_moderator,
    CASES, FEATURED_CASES, STICKER_CAPSULES, RARITY_EMOJIS,
    QUEST_TYPES, GAME_CATALOG,
    get_random_item, get_random_sticker, calculate_item_value,
    generate_skin_float, get_skin_condition,
    ensure_user_exists, get_user_balance, deduct_balance, add_balance,
    convert_decimals, TRADE_UP_PROGRESSION, GOLD_TIER_PROGRESSION,
    STICKER_TRADE_PROGRESSION, GOLD_VALUES, CONDITION_MULTIPLIERS,
    WEAPON_BASE_VALUES, STICKER_VALUES, get_db, init_db, ensure_bot_users,
    SLOT_SYMBOLS, SLOT_PAYOUTS,
    ADMIN_USER_IDS, MODERATOR_USER_IDS,
)

# ─── Populate admin / moderator sets from env ────────────────
if _admin_env:
    ADMIN_USER_IDS.update(
        int(x.strip()) for x in _admin_env.split(',') if x.strip()
    )
if _mod_env:
    MODERATOR_USER_IDS.update(
        int(x.strip()) for x in _mod_env.split(',') if x.strip()
    )
logger.info(f"👑 Admin IDs loaded: {ADMIN_USER_IDS}")

# ─── Stripe (optional) ───────────────────────────────────────
try:
    import stripe
    stripe.api_key = STRIPE_SECRET_KEY
    STRIPE_ENABLED = bool(STRIPE_SECRET_KEY)
except ImportError:
    STRIPE_ENABLED = False

# ============================================================
# LIFESPAN  (startup / shutdown)
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──
    logger.info("🚀 CS2CaseBot web server starting...")

    if not DATABASE_URL:
        logger.error("❌ DATABASE_URL not set — DB features will fail")
    else:
        pool = await init_db(DATABASE_URL)
        await _init_all_tables(pool)
        await ensure_bot_users(pool)

        # ── Admin tables ──
        try:
            from routes.admin import init_admin_tables
            await init_admin_tables()
            logger.info("✅ Admin tables ready")
        except Exception as e:
            logger.warning(f"Admin table init skipped: {e}")

    # Mount battle matchmaking loop
    try:
        from routes.case_battles import battle_manager, start_matchmaking
        start_matchmaking()
        logger.info("⚔️  Battle matchmaking started")
    except Exception as e:
        logger.warning(f"Battle module not loaded: {e}")

    # Keep-alive ping
    asyncio.create_task(_db_keepalive())

    logger.info("✅ Server ready!")
    yield

    # ── Shutdown ──
    logger.info("🛑 Server shutting down...")
    try:
        from routes.case_battles import shutdown_matchmaking
        shutdown_matchmaking()
    except Exception:
        pass
    if shared.db_pool:
        await shared.db_pool.close()

# ============================================================
# APP
# ============================================================

app = FastAPI(
    title="CS2CaseBot API",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# MOUNT GAME ROUTERS
# ============================================================

def _safe_include(module_path: str, attr: str = "router"):
    """Include a router, warn but don't crash if the module isn't written yet."""
    try:
        import importlib
        mod = importlib.import_module(module_path)
        app.include_router(getattr(mod, attr))
        logger.info(f"✅ Router mounted: {module_path}")
    except ModuleNotFoundError:
        logger.warning(f"⏳ Router not yet written, skipping: {module_path}")
    except Exception as e:
        logger.error(f"❌ Failed to mount {module_path}: {e}")

_safe_include("routes.case_battles")
_safe_include("routes.games_easy")
_safe_include("routes.games_medium")
_safe_include("routes.games_hard")
_safe_include("routes.games_heavy")
_safe_include("routes.games_poker")
_safe_include("routes.admin")

@app.get("/admin", include_in_schema=False)
async def page_admin(request: Request):
    user_id = await get_user_id_from_session(request)
    if not user_id or user_id not in ADMIN_USER_IDS:
        return RedirectResponse("/")
    return _html("static/admin.html")

# ============================================================
# STATIC FILES
# ============================================================

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# ============================================================
# PAGE ROUTES  (serve HTML files)
# ============================================================

def _html(path: str) -> HTMLResponse:
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return HTMLResponse(f.read())
    return HTMLResponse("<h1>Page not found</h1>", status_code=404)

@app.get("/",              include_in_schema=False)
async def page_index():        return _html("static/index.html")

@app.get("/battle",        include_in_schema=False)
async def page_battle():       return _html("static/battle.html")

@app.get("/battle-setup",  include_in_schema=False)
async def page_battle_setup(): return _html("static/battle-setup.html")

@app.get("/games",         include_in_schema=False)
async def page_games():        return _html("static/games.html")

# Individual game pages
_GAME_PAGES = [
    "slots", "slots-cs2", "slots-jackpot", "slots-bomb",
    "coinflip", "dice", "mines", "crash", "limbo", "hilo",
    "dragon-tiger", "keno", "plinko", "tower", "shotgun", "ladder-climb",
    "roulette", "slide", "mystery-box", "russian-roulette",
    "baccarat", "blackjack", "live-race", "poker",
]

for _game in _GAME_PAGES:
    # capture in closure
    def _make_handler(g):
        async def handler():
            return _html(f"static/games/{g}.html")
        handler.__name__ = f"page_game_{g.replace('-','_')}"
        return handler
    app.get(f"/games/{_game}", include_in_schema=False)(_make_handler(_game))

# ─── Also serve game pages with .html extension ──────────────
@app.get("/games/{game_name}.html", include_in_schema=False)
async def serve_game_with_ext(game_name: str):
    return _html(f"static/games/{game_name}.html")

# ============================================================
# DATABASE TABLE INIT
# ============================================================

async def _init_all_tables(pool):
    async with pool.acquire() as conn:
        # Users
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id          BIGINT PRIMARY KEY,
                username         TEXT,
                balance          DECIMAL(15,2) DEFAULT 1000,
                credits          INTEGER DEFAULT 0,
                tickets          INTEGER DEFAULT 0,
                total_opens      INTEGER DEFAULT 0,
                total_premium_opens INTEGER DEFAULT 0,
                total_golds      INTEGER DEFAULT 0,
                total_trades     INTEGER DEFAULT 0,
                total_games_played INTEGER DEFAULT 0,
                win_streak       INTEGER DEFAULT 0,
                coinflip_wins    INTEGER DEFAULT 0,
                dice_wins        INTEGER DEFAULT 0,
                mines_wins       INTEGER DEFAULT 0,
                slots_wins       INTEGER DEFAULT 0,
                daily_streak     INTEGER DEFAULT 0,
                last_daily       TIMESTAMP,
                last_hourly      TIMESTAMP,
                last_weekly      TIMESTAMP,
                total_hourly_claimed INTEGER DEFAULT 0,
                total_weekly_claimed INTEGER DEFAULT 0,
                xp               INTEGER DEFAULT 0,
                level            INTEGER DEFAULT 1,
                prestige         INTEGER DEFAULT 0,
                created_at       TIMESTAMP DEFAULT NOW(),
                updated_at       TIMESTAMP DEFAULT NOW(),
                is_banned        BOOLEAN DEFAULT FALSE,
                ban_reason       TEXT,
                ban_expires      TIMESTAMP,
                avatar_url       TEXT
            )
        """)
        # Ensure ban columns exist on older DBs (ALTER TABLE IF NOT EXISTS col)
        for col_sql in [
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_banned BOOLEAN DEFAULT FALSE",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS ban_reason TEXT",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS ban_expires TIMESTAMP",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_url TEXT",
            # NEW: settings and tickets columns
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS settings JSONB DEFAULT '{}'::jsonb",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS tickets INTEGER DEFAULT 0",
        ]:
            try:
                await conn.execute(col_sql)
            except Exception:
                pass
        # Inventory
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS inventory (
                id          SERIAL PRIMARY KEY,
                user_id     BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                item_name   TEXT NOT NULL,
                item_type   TEXT DEFAULT 'weapon',
                rarity      TEXT,
                price       DECIMAL(15,2),
                condition   TEXT,
                is_stattrak BOOLEAN DEFAULT FALSE,
                status      TEXT DEFAULT 'kept',
                case_id     TEXT,
                float_value DECIMAL(10,4),
                created_at  TIMESTAMP DEFAULT NOW()
            )
        """)
        # Guild settings
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id      BIGINT PRIMARY KEY,
                name          TEXT,
                bot_channel_id BIGINT,
                updated_at    TIMESTAMP DEFAULT NOW()
            )
        """)
        # Quests
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS quests (
                id          SERIAL PRIMARY KEY,
                user_id     BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                quest_type  TEXT,
                progress    INTEGER DEFAULT 0,
                required    INTEGER,
                reward      INTEGER,
                completed   BOOLEAN DEFAULT FALSE,
                claimed     BOOLEAN DEFAULT FALSE,
                created_at  TIMESTAMP DEFAULT NOW()
            )
        """)
        # Giveaways
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS giveaways (
                id           SERIAL PRIMARY KEY,
                creator_id   BIGINT REFERENCES users(user_id) ON DELETE SET NULL,
                message_id   BIGINT,
                channel_id   BIGINT,
                prize        TEXT,
                prize_amount DECIMAL(10,2),
                winner_count INTEGER DEFAULT 1,
                end_time     TIMESTAMP,
                ends_at      TIMESTAMP,
                status       TEXT DEFAULT 'active',
                ended        BOOLEAN DEFAULT FALSE,
                created_at   TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS giveaway_entries (
                id           SERIAL PRIMARY KEY,
                giveaway_id  INTEGER REFERENCES giveaways(id) ON DELETE CASCADE,
                user_id      BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                created_at   TIMESTAMP DEFAULT NOW()
            )
        """)
        # Game tables
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS coinflip_games (
                id           SERIAL PRIMARY KEY,
                creator_id   BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                opponent_id  BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                amount       DECIMAL(15,2),
                winner_id    BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                status       TEXT DEFAULT 'waiting',
                created_at   TIMESTAMP DEFAULT NOW(),
                completed_at TIMESTAMP
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS dice_games (
                id          SERIAL PRIMARY KEY,
                user_id     BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                amount      DECIMAL(15,2),
                bet_type    TEXT,
                bet_number  INTEGER,
                roll_number INTEGER,
                result      TEXT,
                multiplier  DECIMAL(10,2),
                created_at  TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS mines_games (
                id              SERIAL PRIMARY KEY,
                user_id         BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                bet_amount      DECIMAL(15,2),
                grid_size       INTEGER DEFAULT 5,
                mine_count      INTEGER DEFAULT 3,
                status          TEXT DEFAULT 'active',
                mine_positions  INTEGER[],
                revealed_tiles  INTEGER[] DEFAULT '{}',
                multiplier      DECIMAL(10,2) DEFAULT 1.0,
                exploded        BOOLEAN DEFAULT FALSE,
                created_at      TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS slots_games (
                id          SERIAL PRIMARY KEY,
                user_id     BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                bet_amount  DECIMAL(15,2),
                spin_result TEXT[],
                multiplier  DECIMAL(10,2),
                win_amount  DECIMAL(15,2),
                created_at  TIMESTAMP DEFAULT NOW()
            )
        """)
        # Generic game log (for new games)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS game_logs (
                id          SERIAL PRIMARY KEY,
                user_id     BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                game_type   TEXT NOT NULL,
                bet_amount  DECIMAL(15,2),
                win_amount  DECIMAL(15,2),
                multiplier  DECIMAL(10,4),
                result      TEXT,
                meta        JSONB,
                created_at  TIMESTAMP DEFAULT NOW()
            )
        """)
        # Crash rounds
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS crash_rounds (
                id          SERIAL PRIMARY KEY,
                room_id     TEXT NOT NULL,
                crash_at    DECIMAL(10,2),
                started_at  TIMESTAMP DEFAULT NOW(),
                ended_at    TIMESTAMP
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS crash_bets (
                id          SERIAL PRIMARY KEY,
                round_id    INTEGER REFERENCES crash_rounds(id) ON DELETE CASCADE,
                user_id     BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                bet_amount  DECIMAL(15,2),
                cashout_at  DECIMAL(10,2),
                win_amount  DECIMAL(15,2),
                status      TEXT DEFAULT 'active',
                created_at  TIMESTAMP DEFAULT NOW()
            )
        """)
        # Live race
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS race_rooms (
                id          SERIAL PRIMARY KEY,
                room_code   TEXT UNIQUE NOT NULL,
                status      TEXT DEFAULT 'waiting',
                bet_amount  DECIMAL(15,2),
                winner_id   BIGINT REFERENCES users(user_id) ON DELETE SET NULL,
                created_at  TIMESTAMP DEFAULT NOW(),
                started_at  TIMESTAMP,
                ended_at    TIMESTAMP
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS race_participants (
                id          SERIAL PRIMARY KEY,
                room_id     INTEGER REFERENCES race_rooms(id) ON DELETE CASCADE,
                user_id     BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                agent_id    TEXT,
                is_bot      BOOLEAN DEFAULT FALSE,
                position    DECIMAL(10,4) DEFAULT 0,
                finished    BOOLEAN DEFAULT FALSE,
                finish_time TIMESTAMP,
                payout      DECIMAL(15,2) DEFAULT 0
            )
        """)
        # Poker
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS poker_tables (
                id          SERIAL PRIMARY KEY,
                room_code   TEXT UNIQUE NOT NULL,
                status      TEXT DEFAULT 'waiting',
                buy_in      DECIMAL(15,2),
                pot         DECIMAL(15,2) DEFAULT 0,
                community   TEXT[],
                phase       TEXT DEFAULT 'waiting',
                created_at  TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS poker_players (
                id          SERIAL PRIMARY KEY,
                table_id    INTEGER REFERENCES poker_tables(id) ON DELETE CASCADE,
                user_id     BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                is_bot      BOOLEAN DEFAULT FALSE,
                cards       TEXT[],
                chips       DECIMAL(15,2),
                bet         DECIMAL(15,2) DEFAULT 0,
                status      TEXT DEFAULT 'active',
                seat        INTEGER
            )
        """)
        # Misc
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_achievements (
                id             SERIAL PRIMARY KEY,
                user_id        BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                achievement_id TEXT,
                unlocked_at    TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_streaks (
                user_id              BIGINT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
                current_streak       INTEGER DEFAULT 0,
                best_streak          INTEGER DEFAULT 0,
                golds_in_streak      INTEGER DEFAULT 0,
                total_session_opens  INTEGER DEFAULT 0,
                current_case_id      TEXT,
                updated_at           TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id         BIGINT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
                theme           TEXT DEFAULT 'casino',
                spin_speed      TEXT DEFAULT 'normal',
                sound_enabled   BOOLEAN DEFAULT TRUE,
                feed_enabled    BOOLEAN DEFAULT TRUE,
                confetti_mode   TEXT DEFAULT 'always',
                updated_at      TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS live_feed (
                id           SERIAL PRIMARY KEY,
                user_id      BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                username     TEXT,
                item_name    TEXT,
                rarity       TEXT,
                rarity_emoji TEXT,
                case_type    TEXT,
                float_value  DECIMAL(10,4),
                created_at   TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS donations (
                id                 SERIAL PRIMARY KEY,
                user_id            BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                amount             DECIMAL(15,2),
                donor_name         TEXT,
                donor_email        TEXT,
                payment_provider   TEXT DEFAULT 'stripe',
                stripe_payment_id  TEXT,
                status             TEXT DEFAULT 'pending',
                created_at         TIMESTAMP DEFAULT NOW(),
                updated_at         TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS ticket_purchases (
                id                SERIAL PRIMARY KEY,
                user_id           BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                amount            INTEGER,
                cost_usd          DECIMAL(10,2),
                stripe_session_id TEXT,
                created_at        TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS skin_upgrades (
                id            SERIAL PRIMARY KEY,
                user_id       BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                item_id       INTEGER,
                input_rarity  TEXT,
                output_rarity TEXT,
                success       BOOLEAN,
                created_at    TIMESTAMP DEFAULT NOW()
            )
        """)
    logger.info("✅ All database tables ready")

# ============================================================
# DB KEEP-ALIVE
# ============================================================

async def _db_keepalive():
    while True:
        await asyncio.sleep(300)
        try:
            pool = await get_db()
            async with pool.acquire() as conn:
                await conn.execute("SELECT 1")
        except Exception as e:
            logger.warning(f"DB keep-alive failed: {e}")

# ============================================================
# AUTH ROUTES
# ============================================================

@app.get("/auth/discord")
async def auth_discord():
    scope = "identify email guilds"
    url = (
        f"https://discord.com/api/oauth2/authorize"
        f"?client_id={DISCORD_CLIENT_ID}"
        f"&redirect_uri={DISCORD_REDIRECT_URI}"
        f"&response_type=code&scope={scope}"
    )
    return RedirectResponse(url)

@app.get("/auth/discord/callback")
@app.get("/auth/callback")   # keep old path as fallback
async def auth_callback(code: str, request: Request, response: Response):
    async with httpx.AsyncClient() as client:
        # Exchange code for token
        token_resp = await client.post(
            "https://discord.com/api/oauth2/token",
            data={
                "client_id":     DISCORD_CLIENT_ID,
                "client_secret": DISCORD_CLIENT_SECRET,
                "grant_type":    "authorization_code",
                "code":          code,
                "redirect_uri":  DISCORD_REDIRECT_URI,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if token_resp.status_code != 200:
            raise HTTPException(400, "OAuth token exchange failed")
        token_data = token_resp.json()

        # Get user info
        user_resp = await client.get(
            "https://discord.com/api/users/@me",
            headers={"Authorization": f"Bearer {token_data['access_token']}"},
        )
        if user_resp.status_code != 200:
            raise HTTPException(400, "Failed to fetch Discord user")
        discord_user = user_resp.json()

    user_id  = int(discord_user["id"])
    username = discord_user.get("global_name") or discord_user.get("username", "Unknown")
    avatar   = discord_user.get("avatar")

    # Upsert user
    pool = await get_db()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (user_id, username, balance, created_at, updated_at)
            VALUES ($1, $2, 1000, NOW(), NOW())
            ON CONFLICT (user_id) DO UPDATE
            SET username = $2, updated_at = NOW()
        """, user_id, username)

    # Create session
    token = secrets.token_urlsafe(32)
    sessions[token] = {
        "user_id":    user_id,
        "username":   username,
        "avatar":     avatar,
        "created_at": datetime.now(),
    }

    resp = RedirectResponse(url="/")
    resp.set_cookie(
        "session_token", token,
        max_age=7 * 24 * 3600,
        httponly=True,
        samesite="lax",
    )
    return resp

@app.post("/api/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get("session_token")
    if token and token in sessions:
        del sessions[token]
    response.delete_cookie("session_token")
    return {"success": True}

@app.get("/auth/logout")
async def auth_logout_get(request: Request, response: Response):
    """GET logout — used by frontend window.location redirects."""
    token = request.cookies.get("session_token")
    if token and token in sessions:
        del sessions[token]
    resp = RedirectResponse(url="/")
    resp.delete_cookie("session_token")
    return resp

# ============================================================
# USER / ME
# ============================================================

@app.get("/api/user/me")
async def get_me(request: Request):
    user_id = await get_user_id_from_session(request)
    if not user_id:
        raise HTTPException(401, "Not authenticated")

    pool = await get_db()
    async with pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT * FROM users WHERE user_id = $1", user_id
        )
        session = sessions.get(request.cookies.get("session_token"), {})

    if not user:
        raise HTTPException(404, "User not found")

    avatar_url = None
    avatar = session.get("avatar")
    if avatar:
        avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar}.png"

    return {
        "user_id":     str(user["user_id"]),
        "username":    user["username"],
        "balance":     float(user["balance"] or 0),
        "tickets":     int(user["tickets"] or 0),
        "xp":          int(user["xp"] or 0),
        "level":       int(user["level"] or 1),
        "prestige":    int(user["prestige"] or 0),
        "total_opens": int(user["total_opens"] or 0),
        "total_golds": int(user["total_golds"] or 0),
        "avatar_url":  avatar_url,
    }

# Alias for frontend compatibility
@app.get("/api/me")
async def get_me_alias(request: Request):
    return await get_me(request)

@app.get("/api/user/me/inventory")
async def get_inventory(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    rarity: Optional[str] = None,
    item_type: Optional[str] = None,
):
    user_id = await require_auth(request)
    pool = await get_db()
    async with pool.acquire() as conn:
        where = ["user_id = $1", "status = 'kept'"]
        params: list = [user_id]
        if rarity:
            params.append(rarity)
            where.append(f"rarity = ${len(params)}")
        if item_type:
            params.append(item_type)
            where.append(f"item_type = ${len(params)}")
        where_sql = " AND ".join(where)
        params += [limit, offset]
        rows = await conn.fetch(f"""
            SELECT * FROM inventory WHERE {where_sql}
            ORDER BY created_at DESC
            LIMIT ${len(params)-1} OFFSET ${len(params)}
        """, *params)
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM inventory WHERE {where_sql}",
            *params[:-2]
        )
    def _enrich(r):
        d = convert_decimals(dict(r))
        d["display_name"] = d.get("item_name", "")
        d["name"]         = d.get("item_name", "")
        return d
    return {
        "items": [_enrich(r) for r in rows],
        "total": int(total or 0),
        "count": int(total or 0),
    }

# ─── New endpoints for frontend ──────────────────────────────

@app.get("/api/user/me/stats")
async def get_user_stats(request: Request):
    user_id = await require_auth(request)
    pool = await get_db()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT total_opens, total_golds, total_trades, daily_streak
            FROM users WHERE user_id = $1
        """, user_id)
        inv = await conn.fetchrow("""
            SELECT COUNT(*) as count, COALESCE(SUM(price), 0) as value
            FROM inventory WHERE user_id = $1 AND status = 'kept'
        """, user_id)
    if not row:
        raise HTTPException(404, "User not found")
    return {
        "total_opens": row["total_opens"] or 0,
        "total_golds": row["total_golds"] or 0,
        "total_trades": row["total_trades"] or 0,
        "daily_streak": row["daily_streak"] or 0,
        "inventory_count": inv["count"] if inv else 0,
        "inventory_value": float(inv["value"]) if inv else 0.0,
    }

@app.get("/api/user/me/tickets")
async def get_tickets(request: Request):
    user_id = await require_auth(request)
    pool = await get_db()
    async with pool.acquire() as conn:
        tickets = await conn.fetchval("SELECT tickets FROM users WHERE user_id = $1", user_id)
    return {"tickets": tickets or 0}

@app.get("/api/user/me/profile")
async def get_profile(request: Request):
    user_id = await require_auth(request)
    pool = await get_db()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT level, prestige, xp FROM users WHERE user_id = $1
        """, user_id)
        if not row:
            raise HTTPException(404, "User not found")
        level = row["level"] or 1
        xp = row["xp"] or 0
        xp_needed = level * 50 + 100
        xp_progress = min(100, (xp / xp_needed) * 100)
    return {
        "level": level,
        "prestige": row["prestige"] or 0,
        "xp": xp,
        "xp_needed": xp_needed,
        "xp_progress": round(xp_progress, 1),
    }

@app.get("/api/user/me/balance")
async def get_balance_alias(request: Request):
    return await get_balance_endpoint(request)

@app.get("/api/user/settings")
async def get_user_settings(request: Request):
    import json as _j
    user_id = await require_auth(request)
    D = {"theme": "casino", "spin_speed": "normal", "sound_enabled": True, "confetti_mode": "always"}
    pool = await get_db()
    async with pool.acquire() as conn:
        raw = await conn.fetchval("SELECT settings FROM users WHERE user_id=$1", user_id)
        if raw is None:
            row = await conn.fetchrow("SELECT * FROM user_settings WHERE user_id=$1", user_id)
            if row:
                return {"theme": row["theme"] or "casino", "spin_speed": row["spin_speed"] or "normal",
                        "sound_enabled": bool(row["sound_enabled"]), "confetti_mode": row["confetti_mode"] or "always"}
            return D
    if isinstance(raw, str):
        try: return {**D, **_j.loads(raw)}
        except: return D
    if isinstance(raw, dict): return {**D, **raw}
    return D

@app.post("/api/user/settings")
async def save_user_settings(request: Request):
    import json as _j
    user_id = await require_auth(request)
    body = await request.json()
    pool = await get_db()
    async with pool.acquire() as conn:
        raw = await conn.fetchval("SELECT settings FROM users WHERE user_id=$1", user_id)
        try: existing = _j.loads(raw) if isinstance(raw, str) else (raw or {})
        except: existing = {}
        existing.update(body)
        await conn.execute("UPDATE users SET settings=$1 WHERE user_id=$2", _j.dumps(existing), user_id)
        try:
            await conn.execute("""
                INSERT INTO user_settings (user_id,theme,spin_speed,sound_enabled,confetti_mode)
                VALUES ($1,$2,$3,$4,$5) ON CONFLICT (user_id) DO UPDATE
                SET theme=$2,spin_speed=$3,sound_enabled=$4,confetti_mode=$5,updated_at=NOW()
            """, user_id, existing.get("theme","casino"), existing.get("spin_speed","normal"),
                bool(existing.get("sound_enabled",True)), existing.get("confetti_mode","always"))
        except: pass
    return {"success": True}

@app.get("/api/user/streak")
async def get_user_streak(request: Request):
    user_id = await require_auth(request)
    pool = await get_db()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM user_streaks WHERE user_id = $1", user_id)
    if not row:
        return {"current_streak": 0, "best_streak": 0, "golds_in_streak": 0, "total_opens": 0}
    return {
        "current_streak": row["current_streak"] or 0,
        "best_streak": row["best_streak"] or 0,
        "golds_in_streak": row["golds_in_streak"] or 0,
        "total_opens": row["total_session_opens"] or 0,
    }

@app.get("/api/user/favorites")
async def get_user_favorites(request: Request):
    user_id = await require_auth(request)
    pool = await get_db()
    async with pool.acquire() as conn:
        try:
            settings_raw = await conn.fetchval("SELECT settings FROM users WHERE user_id = $1", user_id)
            if settings_raw is None:
                return {"favorite_ids": [], "count": 0, "favorites": []}
            # Parse JSON string
            import json
            settings = json.loads(settings_raw) if isinstance(settings_raw, str) else settings_raw
            favs = settings.get("favorites", [])
            # Build case list for frontend
            case_list = []
            for cid in favs:
                case = CASES.get(cid)
                if case:
                    case_list.append({"id": cid, "name": case["name"], "emoji": case.get("emoji", "📦"), "price": case["price"]})
            return {"favorite_ids": favs, "count": len(favs), "favorites": case_list}
        except Exception as e:
            logger.exception("Get favorites error")
            raise HTTPException(500, f"Error loading favorites: {str(e)}")

@app.post("/api/user/favorites/add")
async def add_favorite(request: Request):
    body = await request.json()
    user_id = await require_auth(request)
    case_id = body.get("case_id")
    if not case_id or case_id not in CASES:
        raise HTTPException(400, "Invalid case id")

    pool = await get_db()
    async with pool.acquire() as conn:
        try:
            import json
            settings_raw = await conn.fetchval("SELECT settings FROM users WHERE user_id = $1", user_id)
            if settings_raw is None:
                settings = {}
            elif isinstance(settings_raw, str):
                settings = json.loads(settings_raw)
            else:
                settings = settings_raw

            favs = settings.get("favorites", [])
            if case_id not in favs:
                if len(favs) >= 5:
                    raise HTTPException(400, "Maximum 5 favorites allowed")
                favs.append(case_id)
            settings["favorites"] = favs

            # Store as JSON string
            await conn.execute("UPDATE users SET settings = $1 WHERE user_id = $2", json.dumps(settings), user_id)
            return {"success": True, "favorites": favs}
        except Exception as e:
            logger.exception("Favorite add error")
            raise HTTPException(500, f"Database error: {str(e)}")

@app.post("/api/user/favorites/remove")
async def remove_favorite(request: Request):
    body = await request.json()
    user_id = await require_auth(request)
    case_id = body.get("case_id")
    if not case_id:
        raise HTTPException(400, "Missing case_id")

    pool = await get_db()
    async with pool.acquire() as conn:
        try:
            import json
            settings_raw = await conn.fetchval("SELECT settings FROM users WHERE user_id = $1", user_id)
            if settings_raw is None:
                settings = {}
            else:
                settings = json.loads(settings_raw) if isinstance(settings_raw, str) else settings_raw

            favs = settings.get("favorites", [])
            if case_id in favs:
                favs.remove(case_id)
                settings["favorites"] = favs
                await conn.execute("UPDATE users SET settings = $1 WHERE user_id = $2", json.dumps(settings), user_id)
            return {"success": True, "favorites": favs}
        except Exception as e:
            logger.exception("Remove favorite error")
            raise HTTPException(500, f"Error removing favorite: {str(e)}")

@app.get("/api/user/achievements")
async def get_achievements(request: Request):
    user_id = await require_auth(request)
    pool = await get_db()
    async with pool.acquire() as conn:
        user = await conn.fetchrow("SELECT total_opens, total_golds, total_trades FROM users WHERE user_id = $1", user_id)
        unlocks = await conn.fetch("SELECT achievement_id FROM user_achievements WHERE user_id = $1", user_id)
    unlocked_set = {u["achievement_id"] for u in unlocks}
    # Define achievement list
    achievement_defs = [
        {"id": "first_open", "name": "First Case", "icon": "📦", "description": "Open your first case", "condition": lambda u: u["total_opens"] >= 1},
        {"id": "gold_finder", "name": "Gold Hunter", "icon": "⭐", "description": "Find your first gold", "condition": lambda u: u["total_golds"] >= 1},
        {"id": "case_hunter", "name": "Case Collector", "icon": "📦", "description": "Open 100 cases", "condition": lambda u: u["total_opens"] >= 100},
        {"id": "gold_hoarder", "name": "Gold Hoarder", "icon": "⭐", "description": "Find 10 golds", "condition": lambda u: u["total_golds"] >= 10},
    ]
    achievements = []
    for adef in achievement_defs:
        unlocked = adef["id"] in unlocked_set or (adef["condition"](user) if user else False)
        achievements.append({
            "id": adef["id"],
            "name": adef["name"],
            "icon": adef["icon"],
            "description": adef["description"],
            "unlocked": unlocked,
        })
    return {"achievements": achievements}

# ─── Daily, Cases, Featured, etc. ──────────────────────────

@app.post("/api/daily")
async def claim_daily(request: Request):
    user_id = await require_auth(request)
    pool = await get_db()
    async with pool.acquire() as conn:
        user = await conn.fetchrow("SELECT balance, daily_streak, last_daily FROM users WHERE user_id = $1", user_id)
        if not user:
            raise HTTPException(404, "User not found")
        now = datetime.now()
        last = user["last_daily"]
        streak = user["daily_streak"] or 0
        if last and last.date() == now.date():
            raise HTTPException(400, "Already claimed today")
        if last and (now - last).days == 1:
            streak += 1
        else:
            streak = 1
        reward = 500 + (streak * 100)
        jackpot = random.randint(1, 1000000) == 1
        if jackpot:
            reward += 50000
        await conn.execute("UPDATE users SET balance = balance + $1, daily_streak = $2, last_daily = $3 WHERE user_id = $4",
                           reward, streak, now, user_id)
    return {"success": True, "reward": reward, "streak": streak, "jackpot": jackpot}

@app.get("/api/cases/featured")
async def get_featured_cases():
    featured_ids = FEATURED_CASES
    featured = []
    for cid in featured_ids:
        case = CASES.get(cid)
        if case:
            featured.append({"id": cid, "name": case["name"], "price": case["price"], "emoji": case.get("emoji", "📦")})
    return {"featured": featured}

from shared import CONTAINER_IMAGE_MAP

@app.get("/api/case-image/{case_id}")
async def get_case_image(case_id: str):
    filename = CONTAINER_IMAGE_MAP.get(case_id)
    if not filename:
        # fallback to a generic container image
        return FileResponse("static/images/containers/default.png")
    local_path = f"static/images/containers/{filename}"
    if os.path.exists(local_path):
        return FileResponse(local_path)
    # fallback if file is missing
    return FileResponse("static/images/containers/default.png")

@app.get("/api/premium-cases")
async def get_premium_cases():
    return {"enabled": False, "message": "Premium cases are coming soon!", "cases": []}

# ============================================================
# CASES API (existing)
# ============================================================

@app.get("/api/cases")
async def list_cases():
    return {
        "cases": [
            {"id": k, "name": v["name"], "emoji": v["emoji"], "price": v["price"]}
            for k, v in CASES.items()
        ],
        "featured": FEATURED_CASES,
    }

@app.get("/api/cases/{case_id}")
async def get_case(case_id: str):
    case = CASES.get(case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    return {"id": case_id, **case}

class OpenCaseRequest(BaseModel):
    case_id: str
    quantity: int = 1

@app.post("/api/open-case")
async def open_case(req: OpenCaseRequest, request: Request):
    user_id = await require_auth(request)
    case = CASES.get(req.case_id)
    if not case:
        raise HTTPException(400, "Invalid case")

    qty = max(1, min(req.quantity, 25))
    discount = {1: 1.0, 5: 0.95, 10: 0.90, 15: 0.85, 20: 0.80, 25: 0.75}.get(qty, 1.0)
    total_cost = round(case["price"] * qty * discount, 2)

    pool = await get_db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await ensure_user_exists(user_id, conn=conn)
            ok = await deduct_balance(user_id, total_cost, conn)
            if not ok:
                raise HTTPException(400, "Insufficient balance")

            items = []
            for _ in range(qty):
                item = get_random_item(req.case_id)
                if not item:
                    continue
                row = await conn.fetchrow("""
                    INSERT INTO inventory
                    (user_id, item_name, item_type, rarity, price, condition,
                     is_stattrak, status, case_id, float_value)
                    VALUES ($1,$2,'weapon',$3,$4,$5,$6,'kept',$7,$8)
                    RETURNING id
                """, user_id, item["name"], item["rarity"], item["price"],
                    item["condition"], item["is_stattrak"], req.case_id, item["float"])
                item["id"] = row["id"]
                items.append(item)

                if item["rarity"] == "Gold":
                    await conn.execute(
                        "UPDATE users SET total_golds = total_golds + 1 WHERE user_id = $1",
                        user_id
                    )

            await conn.execute(
                "UPDATE users SET total_opens = total_opens + $1 WHERE user_id = $2",
                qty, user_id
            )
            # Update live feed
            if items:
                best = max(items, key=lambda x: x["price"])
                session_data = sessions.get(request.cookies.get("session_token"), {})
                username = session_data.get("username", "Someone")
                await conn.execute("""
                    INSERT INTO live_feed (user_id, username, item_name, rarity, rarity_emoji, case_type, float_value)
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                """, user_id, username, best["name"], best["rarity"],
                    RARITY_EMOJIS.get(best["rarity"], ""), req.case_id, best["float"])
                # Trim feed to 100 rows
                await conn.execute("""
                    DELETE FROM live_feed WHERE id NOT IN
                    (SELECT id FROM live_feed ORDER BY created_at DESC LIMIT 100)
                """)

    for it in items:
        it.setdefault("display_name", it.get("name", ""))
    return {"success": True, "items": items, "total_cost": total_cost}

# ─── STICKER CAPSULE ──────────────────────────────────────────────
@app.post("/api/sticker")
async def open_sticker(request: Request):
    body = await request.json()
    user_id = await require_auth(request)
    capsule_id = body.get("capsule")
    if not capsule_id or capsule_id not in STICKER_CAPSULES:
        raise HTTPException(400, "Invalid capsule")

    capsule = STICKER_CAPSULES[capsule_id]

    pool = await get_db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await ensure_user_exists(user_id, conn=conn)

            user = await conn.fetchrow("SELECT balance FROM users WHERE user_id = $1", user_id)
            if not user or float(user['balance']) < capsule['price']:
                raise HTTPException(400, "Insufficient balance")

            await conn.execute(
                "UPDATE users SET balance = balance - $1 WHERE user_id = $2",
                capsule['price'], user_id
            )

            sticker = get_random_sticker(capsule_id)
            if not sticker:
                raise HTTPException(500, "Failed to generate sticker")

            row = await conn.fetchrow("""
                INSERT INTO inventory
                    (user_id, item_name, item_type, rarity, price, is_stattrak)
                VALUES ($1, $2, 'sticker', $3, $4, $5)
                RETURNING id
            """, user_id, sticker['name'], sticker['rarity'], sticker['price'], sticker['is_stattrak'])

            sticker['id'] = row['id']   # attach ID for frontend keep/sell

            new_balance = await conn.fetchval("SELECT balance FROM users WHERE user_id = $1", user_id)

            return {
                "success": True,
                "item": sticker,
                "new_balance": float(new_balance)
            }

@app.post("/api/sell-item")
async def sell_item(request: Request):
    body = await request.json()
    user_id = await require_auth(request)
    item_id = body.get("item_id")
    pool = await get_db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            item = await conn.fetchrow(
                "SELECT * FROM inventory WHERE id=$1 AND user_id=$2 AND status='kept'",
                item_id, user_id
            )
            if not item:
                raise HTTPException(404, "Item not found")
            sell_price = round(float(item["price"]) * 0.70, 2)
            await conn.execute("UPDATE inventory SET status='sold' WHERE id=$1", item_id)
            await add_balance(user_id, sell_price, conn)
    return {"success": True, "sell_price": sell_price}

@app.post("/api/keep-item")
async def keep_item(request: Request):
    body = await request.json()
    user_id = await require_auth(request)
    item_id = body.get("item_id")
    pool = await get_db()
    async with pool.acquire() as conn:
        item = await conn.fetchrow(
            "SELECT id FROM inventory WHERE id=$1 AND user_id=$2", item_id, user_id
        )
        if not item:
            raise HTTPException(404, "Item not found")
        await conn.execute("UPDATE inventory SET status='kept' WHERE id=$1", item_id)
    return {"success": True}

# ============================================================
# QUESTS
# ============================================================

@app.get("/api/quests")
async def get_quests(request: Request):
    user_id = await require_auth(request)
    pool = await get_db()
    async with pool.acquire() as conn:
        await ensure_user_exists(user_id, conn=conn)
        # Create today's quests if missing
        last = await conn.fetchrow(
            "SELECT created_at FROM quests WHERE user_id=$1 ORDER BY created_at DESC LIMIT 1",
            user_id
        )
        if not last or last["created_at"].date() < datetime.now().date():
            await conn.execute("DELETE FROM quests WHERE user_id=$1", user_id)
            for qt, qi in QUEST_TYPES.items():
                await conn.execute("""
                    INSERT INTO quests (user_id, quest_type, progress, required, reward)
                    VALUES ($1,$2,0,$3,$4)
                """, user_id, qt, qi["base_required"], qi["base_reward"])
        rows = await conn.fetch(
            "SELECT * FROM quests WHERE user_id=$1 ORDER BY created_at", user_id
        )
    return [dict(r) for r in rows]

@app.post("/api/claim")
async def claim_quests(request: Request):
    user_id = await require_auth(request)
    pool = await get_db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            quests = await conn.fetch(
                "SELECT * FROM quests WHERE user_id=$1 AND completed=true AND claimed=false",
                user_id
            )
            if not quests:
                raise HTTPException(400, "No quests ready to claim")
            total = sum(q["reward"] for q in quests)
            await conn.execute(
                "UPDATE quests SET claimed=true WHERE user_id=$1 AND completed=true AND claimed=false",
                user_id
            )
            await add_balance(user_id, total, conn)
    return {"success": True, "total_reward": total, "message": f"Claimed ${total:,.0f}!"}

# ============================================================
# TRADE-UP
# ============================================================

class TradeRequest(BaseModel):
    rarity: str
    item_ids: List[int]
    is_gold_trade: bool = False

@app.post("/api/quick-trade")
async def quick_trade(req: TradeRequest, request: Request):
    user_id = await require_auth(request)
    rarity_config = {
        "Blue":   {"count": 10, "next": "Purple"},
        "Purple": {"count": 10, "next": "Pink"},
        "Pink":   {"count": 10, "next": "Red"},
        "Gold":   {"count": 5,  "next": "Gold"},
    }
    cfg = rarity_config.get(req.rarity)
    if not cfg:
        raise HTTPException(400, "Invalid rarity")
    if len(req.item_ids) != cfg["count"]:
        raise HTTPException(400, f"Need exactly {cfg['count']} items")

    pool = await get_db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Verify ownership
            for iid in req.item_ids:
                row = await conn.fetchrow(
                    "SELECT id FROM inventory WHERE id=$1 AND user_id=$2 AND rarity=$3 AND status='kept'",
                    iid, user_id, req.rarity
                )
                if not row:
                    raise HTTPException(400, f"Item {iid} not valid")
            # Delete traded items
            await conn.execute(
                f"DELETE FROM inventory WHERE id = ANY($1::int[])", req.item_ids
            )
            # Generate new item
            if req.is_gold_trade and req.rarity == "Gold":
                # Items already deleted — use fixed tier
                old_item = {}
                next_tier = "Rare"  # default progression
                new_item = {
                    "name": f"Mystery Gold {next_tier}",
                    "rarity": "Gold", "condition": "Factory New",
                    "tier": next_tier, "is_stattrak": False, "float": 0.0,
                    "price": float(GOLD_VALUES.get(next_tier, 150)),
                }
            else:
                next_rarity = cfg["next"]
                possible = [
                    i for case in CASES.values()
                    for i in case["items"] if i["rarity"] == next_rarity
                ]
                template = random.choice(possible) if possible else {
                    "name": f"Mystery {next_rarity}", "condition": "Field-Tested", "tier": None
                }
                is_st = random.random() < 0.1
                fv = generate_skin_float()
                cond = get_skin_condition(fv)
                price = calculate_item_value(next_rarity, cond, template.get("tier"), is_st)
                name = f"{'StatTrak™ ' if is_st else ''}{template['name']}"
                new_item = {
                    "name": name, "rarity": next_rarity, "condition": cond,
                    "tier": template.get("tier"), "is_stattrak": is_st,
                    "float": fv, "price": price,
                }
            row = await conn.fetchrow("""
                INSERT INTO inventory (user_id, item_name, item_type, rarity, price, condition,
                    is_stattrak, status, float_value)
                VALUES ($1,$2,'weapon',$3,$4,$5,$6,'kept',$7) RETURNING id
            """, user_id, new_item["name"], new_item["rarity"], new_item["price"],
                new_item["condition"], new_item["is_stattrak"], new_item.get("float", 0.0))
            new_item["id"] = row["id"]
            await conn.execute(
                "UPDATE users SET total_trades=total_trades+1 WHERE user_id=$1", user_id
            )
    return {"success": True, "new_item": new_item,
            "message": f"Traded {cfg['count']} {req.rarity} → {new_item['name']}!"}

# ============================================================
# SKIN UPGRADE
# ============================================================
@app.post("/api/skin-upgrade")
async def skin_upgrade_endpoint(request: Request):
    body = await request.json()
    try:
        user_id = await require_auth(request)
        item_id = body.get("item_id")
        rarity_order = ["Blue", "Purple", "Pink", "Red", "Gold"]
        upgrade_cost  = {"Blue": 10, "Purple": 50, "Pink": 200, "Red": 1000}
        success_odds  = {"Blue": 0.80, "Purple": 0.60, "Pink": 0.40, "Red": 0.25}

        pool = await get_db()
        async with pool.acquire() as conn:
            async with conn.transaction():
                item = await conn.fetchrow(
                    "SELECT * FROM inventory WHERE id=$1 AND user_id=$2 AND status='kept'",
                    item_id, user_id
                )
                if not item:
                    raise HTTPException(404, "Item not found")
                if item["item_type"] != "weapon":
                    raise HTTPException(400, "Only weapon items can be upgraded")
                if item["rarity"] == "Gold":
                    raise HTTPException(400, "Gold items can't be upgraded")

                idx = rarity_order.index(item["rarity"])
                next_rarity = rarity_order[idx + 1]
                cost = upgrade_cost.get(item["rarity"], 10)

                ok = await deduct_balance(user_id, cost, conn)
                if not ok:
                    raise HTTPException(400, f"Need ${cost} to upgrade")

                await conn.execute("DELETE FROM inventory WHERE id=$1", item_id)

                success = random.random() < success_odds.get(item["rarity"], 0.5)

                if success:
                    possible = [
                        i for case in CASES.values()
                        for i in case["items"] if i["rarity"] == next_rarity
                    ]
                    template = random.choice(possible) if possible else {
                        "name": f"Mystery {next_rarity}",
                        "condition": "Field-Tested",
                        "tier": None
                    }
                    is_st = random.random() < 0.1
                    fv = generate_skin_float()
                    cond = get_skin_condition(fv)
                    price = calculate_item_value(next_rarity, cond, template.get("tier"), is_st)
                    name = f"{'StatTrak™ ' if is_st else ''}{template['name']}"

                    await conn.execute("""
                        INSERT INTO inventory
                            (user_id, item_name, item_type, rarity, price,
                             condition, is_stattrak, status, float_value)
                        VALUES ($1,$2,'weapon',$3,$4,$5,$6,'kept',$7)
                    """, user_id, name, next_rarity, price, cond, is_st, fv)

                    await conn.execute("""
                        INSERT INTO skin_upgrades
                            (user_id, item_id, input_rarity, output_rarity, success)
                        VALUES ($1,$2,$3,$4,true)
                    """, user_id, item_id, item["rarity"], next_rarity)

                    return {
                        "success": True,
                        "upgraded": True,
                        "new_rarity": next_rarity,
                        "new_item_name": name,
                        "new_price": price
                    }
                else:
                    await conn.execute("""
                        INSERT INTO skin_upgrades
                            (user_id, item_id, input_rarity, output_rarity, success)
                        VALUES ($1,$2,$3,$4,false)
                    """, user_id, item_id, item["rarity"], next_rarity)

                    return {
                        "success": True,
                        "upgraded": False,
                        "old_item_name": item["item_name"],
                        "cost": cost
                    }
    except Exception as e:
        logger.exception("Skin upgrade error")
        raise HTTPException(500, f"Upgrade error: {str(e)}")

# ============================================================
# BALANCE / CLAIMS
# ============================================================

@app.get("/api/balance")
async def get_balance_endpoint(request: Request):
    user_id = await require_auth(request)
    bal = await get_user_balance(user_id)
    return {"balance": bal}

@app.post("/api/hourly")
async def claim_hourly(request: Request):
    user_id = await require_auth(request)
    pool = await get_db()
    async with pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT last_hourly, total_hourly_claimed FROM users WHERE user_id=$1", user_id
        )
        if not user:
            raise HTTPException(404, "User not found")
        now = datetime.now()
        if user["last_hourly"] and (now - user["last_hourly"]).total_seconds() < 3600:
            remaining = int(3600 - (now - user["last_hourly"]).total_seconds())
            raise HTTPException(400, f"Next claim in {remaining // 60}m {remaining % 60}s")
        total = (user["total_hourly_claimed"] or 0) + 1
        reward = 75 + (250 if total % 10 == 0 else 0)
        await conn.execute("""
            UPDATE users SET balance=balance+$1, last_hourly=$2, total_hourly_claimed=$3
            WHERE user_id=$4
        """, reward, now, total, user_id)
    return {"success": True, "reward": reward, "total_claimed": total}

@app.post("/api/weekly")
async def claim_weekly(request: Request):
    user_id = await require_auth(request)
    pool = await get_db()
    async with pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT last_weekly, total_weekly_claimed FROM users WHERE user_id=$1", user_id
        )
        if not user:
            raise HTTPException(404, "User not found")
        now = datetime.now()
        if user["last_weekly"] and (now - user["last_weekly"]).total_seconds() < 604800:
            remaining = int(604800 - (now - user["last_weekly"]).total_seconds())
            days = remaining // 86400
            hrs  = (remaining % 86400) // 3600
            raise HTTPException(400, f"Next claim in {days}d {hrs}h")
        total = (user["total_weekly_claimed"] or 0) + 1
        reward = 5000
        await conn.execute("""
            UPDATE users SET balance=balance+$1, last_weekly=$2, total_weekly_claimed=$3
            WHERE user_id=$4
        """, reward, now, total, user_id)
    return {"success": True, "reward": reward, "total_claimed": total}

# ============================================================
# LEADERBOARD
# ============================================================

@app.get("/api/leaderboard/{board_type}")
async def leaderboard(board_type: str, limit: int = 10):
    col_map = {
        "money":  ("balance",     "💰"),
        "opens":  ("total_opens", "📦"),
        "golds":  ("total_golds", "⭐"),
        "trades": ("total_trades","🔄"),
    }
    if board_type not in col_map:
        raise HTTPException(400, "Invalid leaderboard type")
    col, _ = col_map[board_type]
    pool = await get_db()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT user_id, username, {col} as value FROM users "
            f"WHERE user_id > 0 ORDER BY {col} DESC LIMIT $1",
            limit
        )
    return {"users": [convert_decimals(dict(r)) for r in rows]}

# ============================================================
# STATS & STREAKS
# ============================================================

@app.get("/api/stats")
async def get_stats(request: Request):
    user_id = await require_auth(request)
    pool = await get_db()
    async with pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE user_id=$1", user_id)
        streak = await conn.fetchrow(
            "SELECT * FROM user_streaks WHERE user_id=$1", user_id
        )
    if not user:
        raise HTTPException(404, "User not found")
    return {
        "total_opens":        int(user["total_opens"] or 0),
        "total_golds":        int(user["total_golds"] or 0),
        "total_trades":       int(user["total_trades"] or 0),
        "total_games_played": int(user["total_games_played"] or 0),
        "level":              int(user["level"] or 1),
        "xp":                 int(user["xp"] or 0),
        "prestige":           int(user["prestige"] or 0),
        "win_streak":         int(user["win_streak"] or 0),
        "current_streak":     int(streak["current_streak"] if streak else 0),
        "best_streak":        int(streak["best_streak"] if streak else 0),
    }

@app.post("/api/user/streak/update")
async def update_streak(request: Request):
    body = await request.json()
    user_id = await require_auth(request)
    is_gold = body.get("is_gold", False)
    pool = await get_db()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT * FROM user_streaks WHERE user_id=$1", user_id
        )
        if existing:
            new_streak = int(existing["current_streak"] or 0) + 1
            best = max(new_streak, int(existing["best_streak"] or 0))
            golds = int(existing["golds_in_streak"] or 0) + (1 if is_gold else 0)
            await conn.execute("""
                UPDATE user_streaks
                SET current_streak=$1, best_streak=$2, golds_in_streak=$3, updated_at=NOW()
                WHERE user_id=$4
            """, new_streak, best, golds, user_id)
        else:
            await conn.execute("""
                INSERT INTO user_streaks (user_id, current_streak, best_streak, golds_in_streak)
                VALUES ($1, 1, 1, $2)
            """, user_id, 1 if is_gold else 0)
            new_streak = 1
    return {"current_streak": new_streak}

# ============================================================
# LIVE FEED
# ============================================================

@app.get("/api/live-feed")
async def live_feed(limit: int = 20):
    pool = await get_db()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM live_feed ORDER BY created_at DESC LIMIT $1", limit
        )
    return [dict(r) for r in rows]

# ============================================================
# SKIN IMAGE
# ============================================================

from shared import get_skin_image_filename

@app.get("/api/skin-image")
async def get_skin_image(name: str):
    filename = get_skin_image_filename(name)
    if filename:
        # Try your local static folder first
        local_path = f"static/images/skins/{filename}"
        if os.path.exists(local_path):
            return FileResponse(local_path)

        # Fallback to the original repo folder (if you haven't copied everything)
        repo_path = f"CS2-Simulator/assets/skins/{filename}"
        if os.path.exists(repo_path):
            return FileResponse(repo_path)

    # Default fallback image
    default = "static/images/default_skin.png"
    if os.path.exists(default):
        return FileResponse(default)

    # If even default is missing, return a 404
    raise HTTPException(404, "Skin image not found")

# ============================================================
# GAMES CATALOG (for hub page)
# ============================================================

@app.get("/api/games/catalog")
async def games_catalog():
    return GAME_CATALOG

# ============================================================
# PREMIUM / TICKETS
# ============================================================

@app.get("/api/premium-status")
async def premium_status():
    return {"enabled": STRIPE_ENABLED, "message": "Premium features require payment setup"}

@app.get("/api/ticket-balance")
async def ticket_balance(request: Request):
    user_id = await require_auth(request)
    pool = await get_db()
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            "SELECT tickets FROM users WHERE user_id=$1", user_id
        )
    return {"tickets": int(val or 0)}

# ============================================================
# GOALS / DONATION TRACKER
# ============================================================

@app.get("/api/goals")
async def get_goals():
    pool = await get_db()
    async with pool.acquire() as conn:
        users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE user_id > 0")
        donated = await conn.fetchval(
            "SELECT COALESCE(SUM(amount),0) FROM donations WHERE status='completed'"
        )
    return {
        "users":     int(users or 0),
        "donations": float(donated or 0),
    }

# ============================================================
# ADMIN ROUTES
# ============================================================

@app.get("/api/admin/stats")
async def admin_stats(request: Request, _=Depends(require_admin)):
    pool = await get_db()
    async with pool.acquire() as conn:
        users     = await conn.fetchval("SELECT COUNT(*) FROM users WHERE user_id > 0")
        eco       = await conn.fetchval("SELECT COALESCE(SUM(balance),0) FROM users WHERE user_id > 0")
        opens     = await conn.fetchval("SELECT COALESCE(SUM(total_opens),0) FROM users")
        golds     = await conn.fetchval("SELECT COALESCE(SUM(total_golds),0) FROM users")
        inv_value = await conn.fetchval("SELECT COALESCE(SUM(price),0) FROM inventory WHERE status='kept'")
    return {
        "total_users":       int(users or 0),
        "total_economy":     float(eco or 0),
        "total_opens":       int(opens or 0),
        "total_golds":       int(golds or 0),
        "total_inv_value":   float(inv_value or 0),
        "sessions_active":   len(sessions),
    }

@app.post("/api/admin/give-balance")
async def admin_give_balance(request: Request, _=Depends(require_admin)):
    body = await request.json()
    target_id = int(body.get("user_id", 0))
    amount    = float(body.get("amount", 0))
    if not target_id or amount <= 0:
        raise HTTPException(400, "Invalid params")
    await add_balance(target_id, amount)
    return {"success": True}

@app.post("/api/admin/reset-balance")
async def admin_reset_balance(request: Request, _=Depends(require_admin)):
    body = await request.json()
    target_id = int(body.get("user_id", 0))
    amount    = float(body.get("amount", 1000))
    pool = await get_db()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET balance=$1 WHERE user_id=$2", amount, target_id
        )
    return {"success": True}

# ============================================================
# STRIPE WEBHOOK
# ============================================================

@app.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    if not STRIPE_ENABLED:
        raise HTTPException(503, "Stripe not configured")
    payload = await request.body()
    sig     = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except Exception:
        raise HTTPException(400, "Invalid webhook")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        meta    = session.get("metadata", {})
        user_id = int(meta.get("user_id", 0))
        tickets = int(meta.get("tickets", 0))
        if user_id and tickets:
            pool = await get_db()
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE users SET tickets=tickets+$1 WHERE user_id=$2",
                    tickets, user_id
                )
    return {"received": True}

# ─── Missing admin settings endpoint ──────────────────────────
@app.get("/api/admin/settings")
async def admin_settings_public(request: Request):
    """Public fallback for admin/settings – returns safe defaults for non‑admins."""
    user_id = await get_user_id_from_session(request)
    if not user_id or user_id not in ADMIN_USER_IDS:
        return {"settings": {"maintenance_mode": "false", "maintenance_message": "We'll be back soon!"}}
    # For admins, fetch real settings from DB if table exists
    pool = await get_db()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT key, value FROM admin_settings")
        settings = {r["key"]: r["value"] for r in rows}
        defaults = {
            "site_name": "CS2CaseBot",
            "default_currency": "$",
            "support_discord_link": "https://discord.gg/mU33pc7TDE",
            "maintenance_mode": "false",
            "maintenance_message": "We'll be back soon!",
        }
        defaults.update(settings)
    return {"settings": defaults}

# ─── Alias for quests (frontend calls /api/user/me/quests) ──
@app.get("/api/user/me/quests")
async def get_quests_alias(request: Request):
    """Alias for /api/quests – frontend compatibility."""
    return await get_quests(request)

# ─── TICKET PURCHASE (stub) ──────────────────────────────────────────
@app.post("/api/buy-tickets")
async def buy_tickets(request: Request):
    raise HTTPException(503, "Ticket purchasing is not available yet")

# ============================================================
# MISSING ALIAS ROUTES  (index.html calls these paths)
# ============================================================

# Games in index.html tab use /api/games/* paths — alias to real routes
@app.post("/api/games/hourly")
async def games_hourly_alias(request: Request):
    """Alias for /api/hourly — index.html games tab."""
    return await claim_hourly(request)

@app.post("/api/games/weekly")
async def games_weekly_alias(request: Request):
    """Alias for /api/weekly — index.html games tab."""
    return await claim_weekly(request)

@app.get("/api/games/stats")
async def games_stats(request: Request):
    """Game W/L stats for the index.html games tab."""
    user_id = await require_auth(request)
    pool = await get_db()
    async with pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT coinflip_wins, dice_wins, mines_wins, slots_wins FROM users WHERE user_id=$1",
            user_id
        )
        # Count losses from game_logs
        cf_loss = await conn.fetchval(
            "SELECT COUNT(*) FROM game_logs WHERE user_id=$1 AND game_type='coinflip' AND result='loss'", user_id
        ) or 0
        dice_loss = await conn.fetchval(
            "SELECT COUNT(*) FROM game_logs WHERE user_id=$1 AND game_type='dice' AND result='loss'", user_id
        ) or 0
        mines_loss = await conn.fetchval(
            "SELECT COUNT(*) FROM game_logs WHERE user_id=$1 AND game_type='mines' AND result='loss'", user_id
        ) or 0
        slots_loss = await conn.fetchval(
            "SELECT COUNT(*) FROM game_logs WHERE user_id=$1 AND game_type='slots' AND result='loss'", user_id
        ) or 0
    if not user:
        return {"coinflip": {"wins": 0, "losses": 0}, "dice": {"wins": 0, "losses": 0},
                "mines": {"wins": 0, "losses": 0}, "slots": {"wins": 0, "losses": 0}}
    return {
        "coinflip": {"wins": int(user["coinflip_wins"] or 0), "losses": int(cf_loss)},
        "dice":     {"wins": int(user["dice_wins"] or 0),     "losses": int(dice_loss)},
        "mines":    {"wins": int(user["mines_wins"] or 0),    "losses": int(mines_loss)},
        "slots":    {"wins": int(user["slots_wins"] or 0),    "losses": int(slots_loss)},
    }

@app.post("/api/games/coinflip/create")
async def coinflip_create(request: Request):
    """Coinflip game in index.html — simple PvC."""
    body = await request.json()
    user_id = await require_auth(request)
    amount = float(body.get("amount", 100))
    if amount < 10:
        raise HTTPException(400, "Minimum bet is $10")
    pool = await get_db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await ensure_user_exists(user_id, conn=conn)
            if not await deduct_balance(user_id, amount, conn):
                raise HTTPException(400, "Insufficient balance")
            user_wins = random.random() < 0.5
            if user_wins:
                win = round(amount * 1.9, 2)   # 5% house edge
                await add_balance(user_id, win, conn)
                await conn.execute("UPDATE users SET coinflip_wins=coinflip_wins+1 WHERE user_id=$1", user_id)
            else:
                win = 0
            await conn.execute("""
                INSERT INTO game_logs (user_id, game_type, bet_amount, win_amount, multiplier, result)
                VALUES ($1,'coinflip',$2,$3,$4,$5)
            """, user_id, amount, win, 1.9 if user_wins else 0, 'win' if user_wins else 'loss')
    return {"success": True, "user_wins": user_wins, "amount": amount, "win": win}

@app.post("/api/games/dice/play")
async def dice_play(request: Request):
    """Dice game in index.html."""
    body = await request.json()
    user_id = await require_auth(request)
    amount     = float(body.get("amount", 100))
    bet_type   = body.get("bet_type", "over")   # 'over' | 'under' | 'exact'
    bet_number = int(body.get("bet_number", 7))
    if amount < 10:
        raise HTTPException(400, "Minimum bet is $10")
    roll = random.randint(2, 12)
    if bet_type == "over":
        win = roll > bet_number
        mult = round(12 / max(1, 12 - bet_number), 2)
    elif bet_type == "under":
        win = roll < bet_number
        mult = round(12 / max(1, bet_number - 1), 2)
    else:   # exact
        win = roll == bet_number
        mult = 10.0
    pool = await get_db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await ensure_user_exists(user_id, conn=conn)
            if not await deduct_balance(user_id, amount, conn):
                raise HTTPException(400, "Insufficient balance")
            win_amount = round(amount * mult * 0.95, 2) if win else 0
            if win:
                await add_balance(user_id, win_amount, conn)
                await conn.execute("UPDATE users SET dice_wins=dice_wins+1 WHERE user_id=$1", user_id)
            await conn.execute("""
                INSERT INTO game_logs (user_id, game_type, bet_amount, win_amount, multiplier, result)
                VALUES ($1,'dice',$2,$3,$4,$5)
            """, user_id, amount, win_amount, mult, 'win' if win else 'loss')
    return {"success": True, "win": win, "roll": roll, "win_amount": win_amount,
            "multiplier": mult, "bet_type": bet_type, "bet_number": bet_number}

@app.post("/api/games/slots/play")
async def slots_play(request: Request):
    """Slots game in index.html."""
    body = await request.json()
    user_id = await require_auth(request)
    amount = float(body.get("amount", 100))
    if amount < 10:
        raise HTTPException(400, "Minimum bet is $10")
    symbols = [random.choice(SLOT_SYMBOLS) for _ in range(3)]
    emojis  = [s["emoji"] for s in symbols]
    combo   = "".join(emojis)
    mult    = SLOT_PAYOUTS.get(combo, 0)
    # Near-miss: two matching but not three
    if not mult and emojis[0] == emojis[1]:
        mult = 0
    win_amount = round(amount * mult * 0.96, 2) if mult else 0
    pool = await get_db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await ensure_user_exists(user_id, conn=conn)
            if not await deduct_balance(user_id, amount, conn):
                raise HTTPException(400, "Insufficient balance")
            if win_amount:
                await add_balance(user_id, win_amount, conn)
                await conn.execute("UPDATE users SET slots_wins=slots_wins+1 WHERE user_id=$1", user_id)
            await conn.execute("""
                INSERT INTO game_logs (user_id, game_type, bet_amount, win_amount, multiplier, result)
                VALUES ($1,'slots',$2,$3,$4,$5)
            """, user_id, amount, win_amount, float(mult), 'win' if win_amount else 'loss')
    return {"success": True, "symbols": emojis, "win_amount": win_amount,
            "multiplier": mult, "bet_amount": amount}

@app.post("/api/games/mines/start")
async def mines_start(request: Request):
    """Mines mini-game in index.html."""
    body = await request.json()
    user_id = await require_auth(request)
    amount     = float(body.get("amount", 100))
    grid_size  = int(body.get("grid_size", 5))
    mine_count = int(body.get("mine_count", 3))
    if amount < 10:
        raise HTTPException(400, "Minimum bet is $10")
    total_tiles = grid_size * grid_size
    mine_positions = random.sample(range(total_tiles), min(mine_count, total_tiles - 1))
    pool = await get_db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await ensure_user_exists(user_id, conn=conn)
            if not await deduct_balance(user_id, amount, conn):
                raise HTTPException(400, "Insufficient balance")
            row = await conn.fetchrow("""
                INSERT INTO mines_games
                    (user_id, bet_amount, grid_size, mine_count, mine_positions, status)
                VALUES ($1,$2,$3,$4,$5,'active') RETURNING id
            """, user_id, amount, grid_size, mine_count, mine_positions)
    return {
        "success": True, "game_id": row["id"], "grid_size": grid_size,
        "mine_count": mine_count, "bet_amount": amount,
        "tiles": [{"index": i, "revealed": False} for i in range(total_tiles)]
    }

@app.post("/api/games/mines/reveal")
async def mines_reveal(request: Request):
    """Reveal a tile in an active mines game."""
    body = await request.json()
    user_id = await require_auth(request)
    game_id  = int(body.get("game_id", 0))
    tile_idx = int(body.get("tile_index", 0))
    pool = await get_db()
    async with pool.acquire() as conn:
        game = await conn.fetchrow(
            "SELECT * FROM mines_games WHERE id=$1 AND user_id=$2 AND status='active'",
            game_id, user_id
        )
        if not game:
            raise HTTPException(404, "Game not found or already ended")
        mine_positions = list(game["mine_positions"])
        revealed       = list(game["revealed_tiles"] or [])
        if tile_idx in mine_positions:
            await conn.execute(
                "UPDATE mines_games SET status='lost', exploded=true WHERE id=$1", game_id
            )
            await conn.execute(
                "INSERT INTO game_logs (user_id,game_type,bet_amount,win_amount,multiplier,result) VALUES ($1,'mines',$2,0,0,'loss')",
                user_id, float(game["bet_amount"])
            )
            return {"success": True, "hit_mine": True, "mine_positions": mine_positions}
        revealed.append(tile_idx)
        safe_count = len(revealed)
        total_safe = game["grid_size"]**2 - game["mine_count"]
        mult = round(1 + (safe_count / total_safe) * 4, 2)
        await conn.execute(
            "UPDATE mines_games SET revealed_tiles=$1, multiplier=$2 WHERE id=$3",
            revealed, mult, game_id
        )
    return {"success": True, "hit_mine": False, "tile_index": tile_idx,
            "safe_count": safe_count, "multiplier": mult, "revealed": revealed}

@app.post("/api/games/mines/cashout")
async def mines_cashout(request: Request):
    """Cash out an active mines game."""
    body = await request.json()
    user_id = await require_auth(request)
    game_id = int(body.get("game_id", 0))
    pool = await get_db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            game = await conn.fetchrow(
                "SELECT * FROM mines_games WHERE id=$1 AND user_id=$2 AND status='active'",
                game_id, user_id
            )
            if not game:
                raise HTTPException(404, "Game not found")
            mult    = float(game["multiplier"] or 1.0)
            bet     = float(game["bet_amount"])
            win     = round(bet * mult * 0.96, 2)
            await add_balance(user_id, win, conn)
            await conn.execute("UPDATE mines_games SET status='won' WHERE id=$1", game_id)
            await conn.execute("UPDATE users SET mines_wins=mines_wins+1 WHERE user_id=$1", user_id)
            await conn.execute("""
                INSERT INTO game_logs (user_id,game_type,bet_amount,win_amount,multiplier,result)
                VALUES ($1,'mines',$2,$3,$4,'win')
            """, user_id, bet, win, mult)
    return {"success": True, "win": win, "multiplier": mult}

@app.post("/api/open-premium-case")
async def open_premium_case(request: Request):
    """Premium case opening — same as regular for now, requires tickets."""
    body = await request.json()
    user_id = await require_auth(request)
    case_id  = body.get("case_id")
    quantity = int(body.get("quantity", 1))
    case = CASES.get(case_id)
    if not case:
        raise HTTPException(400, "Invalid case")
    pool = await get_db()
    async with pool.acquire() as conn:
        tickets = await conn.fetchval("SELECT tickets FROM users WHERE user_id=$1", user_id) or 0
        if tickets < quantity:
            raise HTTPException(400, f"Need {quantity} ticket(s) — you have {tickets}")
        async with conn.transaction():
            await conn.execute(
                "UPDATE users SET tickets=tickets-$1 WHERE user_id=$2", quantity, user_id
            )
            items = []
            for _ in range(quantity):
                item = get_random_item(case_id)
                if not item:
                    continue
                item.setdefault("display_name", item.get("name", ""))
                row = await conn.fetchrow("""
                    INSERT INTO inventory
                    (user_id,item_name,item_type,rarity,price,condition,is_stattrak,status,case_id,float_value)
                    VALUES ($1,$2,'weapon',$3,$4,$5,$6,'kept',$7,$8) RETURNING id
                """, user_id, item["name"], item["rarity"], item["price"],
                    item["condition"], item["is_stattrak"], case_id, item["float"])
                item["id"] = row["id"]
                items.append(item)
            await conn.execute(
                "UPDATE users SET total_opens=total_opens+$1 WHERE user_id=$2", quantity, user_id
            )
    return {"success": True, "items": items, "tickets_used": quantity}

@app.post("/api/sell-batch")
async def sell_batch(request: Request):
    """Sell multiple inventory items at once."""
    body = await request.json()
    user_id  = await require_auth(request)
    item_ids = body.get("item_ids", [])
    if not item_ids:
        raise HTTPException(400, "No items provided")
    if len(item_ids) > 100:
        raise HTTPException(400, "Maximum 100 items per batch")
    pool = await get_db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            rows = await conn.fetch("""
                SELECT id, price FROM inventory
                WHERE id = ANY($1::int[]) AND user_id=$2 AND status='kept'
            """, item_ids, user_id)
            if not rows:
                raise HTTPException(404, "No valid items found")
            total = round(sum(float(r["price"]) * 0.70 for r in rows), 2)
            ids   = [r["id"] for r in rows]
            await conn.execute(
                "UPDATE inventory SET status='sold' WHERE id=ANY($1::int[])", ids
            )
            await add_balance(user_id, total, conn)
    return {
        "success": True,
        "count": len(ids),
        "total_sell_price": total,
        "message": f"Sold {len(ids)} item(s) for ${total:,.2f}",
    }

# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}

@app.get("/api/ping")
async def ping():
    return {"pong": True}
