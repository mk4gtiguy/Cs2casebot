# ============================================================
# SHARED.PY — Single Source of Truth
# CS2CaseBot | All constants, DB, sessions, helpers, bot data
# ============================================================

import random
import time
import logging
import re
import os
import math
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Set, Any, Tuple
from fastapi import HTTPException, Request
import asyncpg

# ─── Logger ─────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("cs2casebot")

# ============================================================
# DATABASE
# ============================================================

db_pool: Optional[asyncpg.Pool] = None

async def get_db() -> asyncpg.Pool:
    if db_pool is None:
        raise RuntimeError("Database pool not initialized")
    return db_pool

async def init_db(database_url: str) -> asyncpg.Pool:
    """Initialize and return the global DB pool."""
    global db_pool
    db_pool = await asyncpg.create_pool(database_url, min_size=2, max_size=20)
    logger.info("✅ Database pool initialized")
    return db_pool

# ============================================================
# SESSIONS
# ============================================================

sessions: Dict[str, Any] = {}
SESSION_TTL = 7 * 24 * 3600  # 7 days

def clean_expired_sessions():
    now = datetime.now()
    expired = [
        k for k, v in sessions.items()
        if (now - v.get("created_at", now)).total_seconds() > SESSION_TTL
    ]
    for k in expired:
        del sessions[k]

async def get_user_id_from_session(request: Request) -> Optional[int]:
    session_token = request.cookies.get("session_token")
    if not session_token or session_token not in sessions:
        return None
    clean_expired_sessions()
    return sessions[session_token]["user_id"]

async def require_auth(request: Request) -> int:
    user_id = await get_user_id_from_session(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user_id

# ============================================================
# ADMIN / MODERATOR
# ============================================================

ADMIN_USER_IDS: Set[int] = set()
MODERATOR_USER_IDS: Set[int] = set()

async def require_admin(request: Request) -> int:
    user_id = await get_user_id_from_session(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if user_id not in ADMIN_USER_IDS:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user_id

async def require_admin_or_moderator(request: Request) -> int:
    user_id = await get_user_id_from_session(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if user_id not in ADMIN_USER_IDS and user_id not in MODERATOR_USER_IDS:
        raise HTTPException(status_code=403, detail="Admin or Moderator access required")
    return user_id

# ============================================================
# BOT ACCOUNTS  (battles + games)
# ============================================================

BOT_IDS = {
    'normal': -1,
    'hard':   -2,
    'expert': -3,
}

BOT_NAMES = {
    -1: '🤖 Bot [Normal]',
    -2: '😈 Bot [Hard]',
    -3: '👹 Bot [Expert]',
}

BOT_STATS = {
    -1: {
        'balance': 250_000, 'total_opens': 800,  'total_golds': 80,
        'total_games_played': 1_200, 'win_streak': 15,
        'coinflip_wins': 100, 'dice_wins': 90, 'mines_wins': 70, 'slots_wins': 60,
    },
    -2: {
        'balance': 500_000, 'total_opens': 1_500, 'total_golds': 200,
        'total_games_played': 2_500, 'win_streak': 30,
        'coinflip_wins': 200, 'dice_wins': 180, 'mines_wins': 150, 'slots_wins': 120,
    },
    -3: {
        'balance': 1_000_000, 'total_opens': 3_000, 'total_golds': 500,
        'total_games_played': 5_000, 'win_streak': 50,
        'coinflip_wins': 450, 'dice_wins': 400, 'mines_wins': 350, 'slots_wins': 300,
    },
}

# CS2 Agent characters for Live Race & other games
RACE_AGENTS = [
    {'id': 'sas',       'name': 'SAS Operator',      'emoji': '🟢', 'color': '#4caf50'},
    {'id': 'phoenix',   'name': 'Phoenix Operative',  'emoji': '🔴', 'color': '#f44336'},
    {'id': 'swat',      'name': 'SWAT Commander',     'emoji': '🔵', 'color': '#2196f3'},
    {'id': 'guerrilla', 'name': 'Guerrilla Warfare',  'emoji': '🟡', 'color': '#ffd700'},
    {'id': 'ksk',       'name': 'KSK Operator',       'emoji': '🟣', 'color': '#9c27b0'},
    {'id': 'seal',      'name': 'SEAL Frogman',       'emoji': '🩵', 'color': '#00bcd4'},
    {'id': 'ksm',       'name': 'Sabre CT',           'emoji': '🟠', 'color': '#ff9800'},
    {'id': 'ground',    'name': 'Ground Rebel',       'emoji': '⚪', 'color': '#9e9e9e'},
]

async def ensure_bot_users(pool: asyncpg.Pool):
    """Insert or refresh all bot users in the DB."""
    async with pool.acquire() as conn:
        for bot_id, name in BOT_NAMES.items():
            stats = BOT_STATS[bot_id]
            exists = await conn.fetchval(
                "SELECT 1 FROM users WHERE user_id = $1", bot_id
            )
            if not exists:
                await conn.execute("""
                    INSERT INTO users (
                        user_id, username, balance, total_opens, total_golds,
                        total_games_played, win_streak, coinflip_wins, dice_wins,
                        mines_wins, slots_wins, created_at, updated_at
                    ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,NOW(),NOW())
                """,
                    bot_id, name,
                    stats['balance'], stats['total_opens'], stats['total_golds'],
                    stats['total_games_played'], stats['win_streak'],
                    stats['coinflip_wins'], stats['dice_wins'],
                    stats['mines_wins'], stats['slots_wins'],
                )
                logger.info(f"✅ Created bot user: {name}")
            else:
                await conn.execute("""
                    UPDATE users SET
                        balance=$1, total_opens=$2, total_golds=$3,
                        total_games_played=$4, win_streak=$5,
                        coinflip_wins=$6, dice_wins=$7,
                        mines_wins=$8, slots_wins=$9, updated_at=NOW()
                    WHERE user_id=$10
                """,
                    stats['balance'], stats['total_opens'], stats['total_golds'],
                    stats['total_games_played'], stats['win_streak'],
                    stats['coinflip_wins'], stats['dice_wins'],
                    stats['mines_wins'], stats['slots_wins'], bot_id,
                )

# ============================================================
# RARITY & VALUE CONSTANTS
# ============================================================

RARITY_EMOJIS      = {"Blue": "🟦", "Purple": "🟪", "Pink": "💗", "Red": "🔴", "Gold": "⭐"}
RARITY_COLORS      = {"Blue": "#4488ff", "Purple": "#aa00ff", "Pink": "#ff69b4", "Red": "#ff4444", "Gold": "#ffd700"}
WEAPON_BASE_VALUES = {"Blue": 0.25, "Purple": 1.00, "Pink": 4.00, "Red": 20.00}
GOLD_VALUES        = {"Common": 150, "Rare": 300, "Epic": 600, "Legendary": 1000, "Mythic": 2500}
CONDITION_MULTIPLIERS = {
    "Factory New": 2.0, "Minimal Wear": 1.5,
    "Field-Tested": 1.0, "Well-Worn": 0.75, "Battle-Scarred": 0.5
}
DROP_RATES         = {"Gold": 2.6, "Red": 2.5, "Pink": 2.5, "Purple": 5.0, "Blue": 87.4}
GOLD_TIER_PROGRESSION  = ["Common", "Rare", "Epic", "Legendary", "Mythic"]
TRADE_UP_PROGRESSION   = {"Blue": "Purple", "Purple": "Pink", "Pink": "Red", "Red": "Gold"}
STICKER_TRADE_PROGRESSION = {
    "⭐": "✨", "✨": "💫", "💫": "🔥",
    "🔥": "👑 Common", "👑 Common": "👑 Rare",
    "👑 Rare": "👑 Epic", "👑 Epic": "👑 Legendary"
}

# ============================================================
# FEATURED CASES
# ============================================================

FEATURED_CASES = [
    "kilowatt_case", "gallery_case", "fever_case",
    "cs20_case", "spectrum_2_case",
    "operation_riptide_case", "dreams_and_nightmares_case",
]

# ============================================================
# CASES DATA — 37 Real CS2 Cases
# ============================================================

CASES = {
    "cs:go_weapon_case": {
        "name": "CS:GO Weapon Case", "emoji": "📦", "price": 2.0,
        "items": [
            {"name": "MP7 | Skulls",           "rarity": "Blue",   "condition": "Battle-Scarred"},
            {"name": "AUG | Wings",             "rarity": "Blue",   "condition": "Battle-Scarred"},
            {"name": "SG 553 | Ultraviolet",    "rarity": "Blue",   "condition": "Well-Worn"},
            {"name": "Glock-18 | Dragon Tattoo","rarity": "Purple", "condition": "Well-Worn"},
            {"name": "USP-S | Dark Water",      "rarity": "Purple", "condition": "Well-Worn"},
            {"name": "M4A1-S | Dark Water",     "rarity": "Purple", "condition": "Battle-Scarred"},
            {"name": "AK-47 | Case Hardened",   "rarity": "Pink",   "condition": "Well-Worn"},
            {"name": "Desert Eagle | Hypnotic", "rarity": "Pink",   "condition": "Minimal Wear"},
            {"name": "★ Bayonet",               "rarity": "Gold",   "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Fade",        "rarity": "Gold",   "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Slaughter",   "rarity": "Gold",   "tier": "Legendary", "condition": "Factory New"},
        ]
    },
    "esports_2013_case": {
        "name": "eSports 2013 Case", "emoji": "🎯", "price": 2.0,
        "items": [
            {"name": "M4A4 | Faded Zebra",      "rarity": "Blue",   "condition": "Factory New"},
            {"name": "MAG-7 | Memento",         "rarity": "Blue",   "condition": "Minimal Wear"},
            {"name": "FAMAS | Doomkitty",       "rarity": "Blue",   "condition": "Field-Tested"},
            {"name": "Galil AR | Orange DDPAT", "rarity": "Purple", "condition": "Well-Worn"},
            {"name": "Sawed-Off | Orange DDPAT","rarity": "Purple", "condition": "Well-Worn"},
            {"name": "P250 | Splash",           "rarity": "Purple", "condition": "Field-Tested"},
            {"name": "AK-47 | Red Laminate",    "rarity": "Pink",   "condition": "Factory New"},
            {"name": "AWP | BOOM",              "rarity": "Pink",   "condition": "Factory New"},
            {"name": "★ Bayonet",               "rarity": "Gold",   "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Fade",        "rarity": "Gold",   "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Slaughter",   "rarity": "Gold",   "tier": "Legendary", "condition": "Factory New"},
        ]
    },
    "operation_phoenix_weapon_case": {
        "name": "Operation Phoenix Weapon Case", "emoji": "⚡", "price": 2.5,
        "items": [
            {"name": "UMP-45 | Corporal",       "rarity": "Blue",   "condition": "Well-Worn"},
            {"name": "Negev | Terrain",         "rarity": "Blue",   "condition": "Well-Worn"},
            {"name": "Tec-9 | Sandstorm",       "rarity": "Blue",   "condition": "Factory New"},
            {"name": "MAG-7 | Heaven Guard",    "rarity": "Blue",   "condition": "Well-Worn"},
            {"name": "MAC-10 | Heat",           "rarity": "Purple", "condition": "Battle-Scarred"},
            {"name": "SG 553 | Pulse",          "rarity": "Purple", "condition": "Minimal Wear"},
            {"name": "FAMAS | Sergeant",        "rarity": "Purple", "condition": "Battle-Scarred"},
            {"name": "USP-S | Guardian",        "rarity": "Purple", "condition": "Field-Tested"},
            {"name": "★ Bayonet",               "rarity": "Gold",   "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Fade",        "rarity": "Gold",   "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Slaughter",   "rarity": "Gold",   "tier": "Legendary", "condition": "Factory New"},
        ]
    },
    "huntsman_weapon_case": {
        "name": "Huntsman Weapon Case", "emoji": "🔥", "price": 2.5,
        "items": [
            {"name": "Tec-9 | Isaac",           "rarity": "Blue",   "condition": "Battle-Scarred"},
            {"name": "SSG 08 | Slashed",        "rarity": "Blue",   "condition": "Minimal Wear"},
            {"name": "Galil AR | Kami",         "rarity": "Blue",   "condition": "Factory New"},
            {"name": "CZ75-Auto | Twist",       "rarity": "Blue",   "condition": "Well-Worn"},
            {"name": "P90 | Module",            "rarity": "Blue",   "condition": "Well-Worn"},
            {"name": "P2000 | Pulse",           "rarity": "Blue",   "condition": "Well-Worn"},
            {"name": "AUG | Torque",            "rarity": "Purple", "condition": "Minimal Wear"},
            {"name": "PP-Bizon | Antique",      "rarity": "Purple", "condition": "Minimal Wear"},
            {"name": "★ Huntsman Knife",              "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Huntsman Knife | Fade",       "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Huntsman Knife | Crimson Web","rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
        ]
    },
    "operation_breakout_weapon_case": {
        "name": "Operation Breakout Weapon Case", "emoji": "💎", "price": 2.5,
        "items": [
            {"name": "MP7 | Urban Hazard",      "rarity": "Blue",   "condition": "Well-Worn"},
            {"name": "Negev | Desert-Strike",   "rarity": "Blue",   "condition": "Factory New"},
            {"name": "P2000 | Ivory",           "rarity": "Blue",   "condition": "Field-Tested"},
            {"name": "SSG 08 | Abyss",          "rarity": "Blue",   "condition": "Field-Tested"},
            {"name": "UMP-45 | Labyrinth",      "rarity": "Blue",   "condition": "Well-Worn"},
            {"name": "PP-Bizon | Osiris",       "rarity": "Purple", "condition": "Field-Tested"},
            {"name": "CZ75-Auto | Tigris",      "rarity": "Purple", "condition": "Factory New"},
            {"name": "Nova | Koi",              "rarity": "Purple", "condition": "Field-Tested"},
            {"name": "★ Butterfly Knife",              "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Butterfly Knife | Fade",       "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Butterfly Knife | Crimson Web","rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
        ]
    },
    "esports_2014_summer_case": {
        "name": "eSports 2014 Summer Case", "emoji": "🌟", "price": 2.0,
        "items": [
            {"name": "SSG 08 | Dark Water",     "rarity": "Blue",   "condition": "Battle-Scarred"},
            {"name": "MAC-10 | Ultraviolet",    "rarity": "Blue",   "condition": "Battle-Scarred"},
            {"name": "USP-S | Blood Tiger",     "rarity": "Blue",   "condition": "Well-Worn"},
            {"name": "CZ75-Auto | Hexane",      "rarity": "Blue",   "condition": "Factory New"},
            {"name": "Negev | Bratatat",        "rarity": "Blue",   "condition": "Minimal Wear"},
            {"name": "XM1014 | Red Python",     "rarity": "Blue",   "condition": "Field-Tested"},
            {"name": "PP-Bizon | Blue Streak",  "rarity": "Purple", "condition": "Minimal Wear"},
            {"name": "P90 | Virus",             "rarity": "Purple", "condition": "Well-Worn"},
            {"name": "★ Bayonet",               "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Fade",        "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Slaughter",   "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
        ]
    },
    "operation_vanguard_weapon_case": {
        "name": "Operation Vanguard Weapon Case", "emoji": "🎨", "price": 2.5,
        "items": [
            {"name": "G3SG1 | Murky",           "rarity": "Blue",   "condition": "Well-Worn"},
            {"name": "MAG-7 | Firestarter",     "rarity": "Blue",   "condition": "Field-Tested"},
            {"name": "MP9 | Dart",              "rarity": "Blue",   "condition": "Field-Tested"},
            {"name": "Five-SeveN | Urban Hazard","rarity": "Blue",  "condition": "Well-Worn"},
            {"name": "UMP-45 | Delusion",       "rarity": "Blue",   "condition": "Battle-Scarred"},
            {"name": "Glock-18 | Grinder",      "rarity": "Purple", "condition": "Well-Worn"},
            {"name": "M4A1-S | Basilisk",       "rarity": "Purple", "condition": "Well-Worn"},
            {"name": "M4A4 | Griffin",          "rarity": "Purple", "condition": "Factory New"},
            {"name": "★ Bayonet",               "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Fade",        "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Slaughter",   "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
        ]
    },
    "chroma_case": {
        "name": "Chroma Case", "emoji": "🌈", "price": 2.0,
        "items": [
            {"name": "Glock-18 | Catacombs",        "rarity": "Blue",   "condition": "Field-Tested"},
            {"name": "M249 | System Lock",           "rarity": "Blue",   "condition": "Battle-Scarred"},
            {"name": "MP9 | Deadly Poison",          "rarity": "Blue",   "condition": "Factory New"},
            {"name": "SCAR-20 | Grotto",             "rarity": "Blue",   "condition": "Battle-Scarred"},
            {"name": "XM1014 | Quicksilver",         "rarity": "Blue",   "condition": "Well-Worn"},
            {"name": "Dual Berettas | Urban Shock",  "rarity": "Purple", "condition": "Field-Tested"},
            {"name": "Desert Eagle | Naga",          "rarity": "Purple", "condition": "Factory New"},
            {"name": "MAC-10 | Malachite",           "rarity": "Purple", "condition": "Minimal Wear"},
            {"name": "★ Bayonet | Marble Fade",      "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Tiger Tooth",      "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Doppler",          "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
        ]
    },
    "chroma_2_case": {
        "name": "Chroma 2 Case", "emoji": "💥", "price": 2.0,
        "items": [
            {"name": "AK-47 | Elite Build",     "rarity": "Blue",   "condition": "Minimal Wear"},
            {"name": "MP7 | Armor Core",        "rarity": "Blue",   "condition": "Factory New"},
            {"name": "Desert Eagle | Bronze Deco","rarity": "Blue",  "condition": "Minimal Wear"},
            {"name": "P250 | Valence",          "rarity": "Blue",   "condition": "Battle-Scarred"},
            {"name": "Negev | Man-o'-war",      "rarity": "Blue",   "condition": "Battle-Scarred"},
            {"name": "Sawed-Off | Origami",     "rarity": "Blue",   "condition": "Battle-Scarred"},
            {"name": "AWP | Worm God",          "rarity": "Purple", "condition": "Factory New"},
            {"name": "MAG-7 | Heat",            "rarity": "Purple", "condition": "Field-Tested"},
            {"name": "★ Bayonet | Marble Fade", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Tiger Tooth", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Doppler",     "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
        ]
    },
    "falchion_case": {
        "name": "Falchion Case", "emoji": "🌅", "price": 2.0,
        "items": [
            {"name": "Galil AR | Rocket Pop",   "rarity": "Blue",   "condition": "Minimal Wear"},
            {"name": "Glock-18 | Bunsen Burner","rarity": "Blue",   "condition": "Factory New"},
            {"name": "Nova | Ranger",           "rarity": "Blue",   "condition": "Factory New"},
            {"name": "P90 | Elite Build",       "rarity": "Blue",   "condition": "Well-Worn"},
            {"name": "UMP-45 | Riot",           "rarity": "Blue",   "condition": "Minimal Wear"},
            {"name": "USP-S | Torque",          "rarity": "Blue",   "condition": "Battle-Scarred"},
            {"name": "FAMAS | Neural Net",      "rarity": "Purple", "condition": "Battle-Scarred"},
            {"name": "M4A4 | Evil Daimyo",      "rarity": "Purple", "condition": "Battle-Scarred"},
            {"name": "★ Falchion Knife",              "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Falchion Knife | Fade",       "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Falchion Knife | Crimson Web","rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
        ]
    },
    "shadow_case": {
        "name": "Shadow Case", "emoji": "⚠️", "price": 2.0,
        "items": [
            {"name": "Dual Berettas | Dualing Dragons","rarity": "Blue",  "condition": "Battle-Scarred"},
            {"name": "FAMAS | Survivor Z",             "rarity": "Blue",  "condition": "Field-Tested"},
            {"name": "Glock-18 | Wraiths",             "rarity": "Blue",  "condition": "Battle-Scarred"},
            {"name": "MAC-10 | Rangeen",               "rarity": "Blue",  "condition": "Battle-Scarred"},
            {"name": "MAG-7 | Cobalt Core",            "rarity": "Blue",  "condition": "Factory New"},
            {"name": "SCAR-20 | Green Marine",         "rarity": "Blue",  "condition": "Minimal Wear"},
            {"name": "XM1014 | Scumbria",              "rarity": "Blue",  "condition": "Battle-Scarred"},
            {"name": "Galil AR | Stone Cold",          "rarity": "Purple","condition": "Minimal Wear"},
            {"name": "★ Shadow Daggers",               "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Shadow Daggers | Fade",        "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Shadow Daggers | Crimson Web", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
        ]
    },
    "revolver_case": {
        "name": "Revolver Case", "emoji": "🤲", "price": 2.0,
        "items": [
            {"name": "R8 Revolver | Crimson Web",  "rarity": "Blue",   "condition": "Battle-Scarred"},
            {"name": "AUG | Ricochet",             "rarity": "Blue",   "condition": "Battle-Scarred"},
            {"name": "Desert Eagle | Corinthian",  "rarity": "Blue",   "condition": "Field-Tested"},
            {"name": "P2000 | Imperial",           "rarity": "Blue",   "condition": "Factory New"},
            {"name": "Sawed-Off | Yorick",         "rarity": "Blue",   "condition": "Well-Worn"},
            {"name": "SCAR-20 | Outbreak",         "rarity": "Blue",   "condition": "Battle-Scarred"},
            {"name": "PP-Bizon | Fuel Rod",        "rarity": "Purple", "condition": "Factory New"},
            {"name": "Five-SeveN | Retrobution",   "rarity": "Purple", "condition": "Battle-Scarred"},
            {"name": "★ Bayonet",                  "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Fade",           "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Slaughter",      "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
        ]
    },
    "operation_wildfire_case": {
        "name": "Operation Wildfire Case", "emoji": "🎪", "price": 3.0,
        "items": [
            {"name": "PP-Bizon | Photic Zone",     "rarity": "Blue",   "condition": "Battle-Scarred"},
            {"name": "Dual Berettas | Cartel",     "rarity": "Blue",   "condition": "Well-Worn"},
            {"name": "MAC-10 | Lapis Gator",       "rarity": "Blue",   "condition": "Well-Worn"},
            {"name": "SSG 08 | Necropos",          "rarity": "Blue",   "condition": "Factory New"},
            {"name": "Tec-9 | Jambiya",            "rarity": "Blue",   "condition": "Well-Worn"},
            {"name": "USP-S | Lead Conduit",       "rarity": "Blue",   "condition": "Battle-Scarred"},
            {"name": "FAMAS | Valence",            "rarity": "Purple", "condition": "Minimal Wear"},
            {"name": "Five-SeveN | Triumvirate",   "rarity": "Purple", "condition": "Minimal Wear"},
            {"name": "★ Bowie Knife",              "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bowie Knife | Fade",       "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bowie Knife | Crimson Web","rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
        ]
    },
    "chroma_3_case": {
        "name": "Chroma 3 Case", "emoji": "🏹", "price": 2.0,
        "items": [
            {"name": "Dual Berettas | Ventilators","rarity": "Blue",  "condition": "Field-Tested"},
            {"name": "G3SG1 | Orange Crash",       "rarity": "Blue",  "condition": "Field-Tested"},
            {"name": "M249 | Spectre",             "rarity": "Blue",  "condition": "Factory New"},
            {"name": "MP9 | Bioleak",              "rarity": "Blue",  "condition": "Well-Worn"},
            {"name": "P2000 | Oceanic",            "rarity": "Blue",  "condition": "Factory New"},
            {"name": "Sawed-Off | Fubar",          "rarity": "Blue",  "condition": "Well-Worn"},
            {"name": "SG 553 | Atlas",             "rarity": "Blue",  "condition": "Factory New"},
            {"name": "CZ75-Auto | Red Astor",      "rarity": "Purple","condition": "Field-Tested"},
            {"name": "★ Bayonet | Marble Fade",    "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Tiger Tooth",    "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Doppler",        "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
        ]
    },
    "gamma_case": {
        "name": "Gamma Case", "emoji": "🗡️", "price": 2.5,
        "items": [
            {"name": "Five-SeveN | Violent Daimyo","rarity": "Blue",  "condition": "Factory New"},
            {"name": "MAC-10 | Carnivore",         "rarity": "Blue",  "condition": "Minimal Wear"},
            {"name": "Nova | Exo",                 "rarity": "Blue",  "condition": "Minimal Wear"},
            {"name": "P250 | Iron Clad",           "rarity": "Blue",  "condition": "Field-Tested"},
            {"name": "PP-Bizon | Harvester",       "rarity": "Blue",  "condition": "Factory New"},
            {"name": "SG 553 | Aerial",            "rarity": "Blue",  "condition": "Well-Worn"},
            {"name": "Tec-9 | Ice Cap",            "rarity": "Blue",  "condition": "Battle-Scarred"},
            {"name": "AUG | Aristocrat",           "rarity": "Purple","condition": "Field-Tested"},
            {"name": "★ Bayonet | Gamma Doppler",  "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Gamma Doppler",  "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Gamma Doppler",  "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
        ]
    },
    "gamma_2_case": {
        "name": "Gamma 2 Case", "emoji": "🛡️", "price": 2.5,
        "items": [
            {"name": "CZ75-Auto | Imprint",        "rarity": "Blue",  "condition": "Factory New"},
            {"name": "Five-SeveN | Scumbria",      "rarity": "Blue",  "condition": "Well-Worn"},
            {"name": "G3SG1 | Ventilator",         "rarity": "Blue",  "condition": "Factory New"},
            {"name": "Negev | Dazzle",             "rarity": "Blue",  "condition": "Field-Tested"},
            {"name": "P90 | Grim",                 "rarity": "Blue",  "condition": "Field-Tested"},
            {"name": "UMP-45 | Briefing",          "rarity": "Blue",  "condition": "Well-Worn"},
            {"name": "XM1014 | Slipstream",        "rarity": "Blue",  "condition": "Factory New"},
            {"name": "Desert Eagle | Directive",   "rarity": "Purple","condition": "Minimal Wear"},
            {"name": "★ Bayonet | Gamma Doppler",  "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Gamma Doppler",  "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Gamma Doppler",  "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
        ]
    },
    "glove_case": {
        "name": "Glove Case", "emoji": "👑", "price": 4.0,
        "items": [
            {"name": "CZ75-Auto | Polymer",            "rarity": "Blue",  "condition": "Factory New"},
            {"name": "Glock-18 | Ironwork",            "rarity": "Blue",  "condition": "Minimal Wear"},
            {"name": "MP7 | Cirrus",                   "rarity": "Blue",  "condition": "Factory New"},
            {"name": "Galil AR | Black Sand",          "rarity": "Blue",  "condition": "Battle-Scarred"},
            {"name": "MP9 | Sand Scale",               "rarity": "Blue",  "condition": "Factory New"},
            {"name": "MAG-7 | Sonar",                  "rarity": "Blue",  "condition": "Well-Worn"},
            {"name": "P2000 | Turf",                   "rarity": "Blue",  "condition": "Battle-Scarred"},
            {"name": "Dual Berettas | Royal Consorts", "rarity": "Purple","condition": "Factory New"},
            {"name": "★ Bloodhound Gloves | Snakebite","rarity": "Gold",  "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bloodhound Gloves | Bronzed",  "rarity": "Gold",  "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bloodhound Gloves | Charred",  "rarity": "Gold",  "tier": "Legendary", "condition": "Factory New"},
        ]
    },
    "spectrum_case": {
        "name": "Spectrum Case", "emoji": "🎰", "price": 2.5,
        "items": [
            {"name": "PP-Bizon | Jungle Slipstream","rarity": "Blue",  "condition": "Battle-Scarred"},
            {"name": "Five-SeveN | Boost Protocol", "rarity": "Blue",  "condition": "Factory New"},
            {"name": "Galil AR | Crimson Tsunami",  "rarity": "Blue",  "condition": "Field-Tested"},
            {"name": "SCAR-20 | Bloodsport",        "rarity": "Blue",  "condition": "Factory New"},
            {"name": "Tec-9 | Decimator",           "rarity": "Blue",  "condition": "Factory New"},
            {"name": "UMP-45 | Primal Saber",       "rarity": "Blue",  "condition": "Minimal Wear"},
            {"name": "G3SG1 | Chronos",             "rarity": "Purple","condition": "Factory New"},
            {"name": "AUG | Midnight Lily",         "rarity": "Purple","condition": "Factory New"},
            {"name": "★ Navaja Knife",              "rarity": "Gold",  "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Navaja Knife | Fade",       "rarity": "Gold",  "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Navaja Knife | Crimson Web","rarity": "Gold",  "tier": "Legendary", "condition": "Factory New"},
        ]
    },
    "operation_hydra_case": {
        "name": "Operation Hydra Case", "emoji": "🎲", "price": 2.0,
        "items": [
            {"name": "AUG | Stymphalian",           "rarity": "Blue",  "condition": "Battle-Scarred"},
            {"name": "Five-SeveN | Hyper Beast",    "rarity": "Blue",  "condition": "Minimal Wear"},
            {"name": "G3SG1 | Stinger",             "rarity": "Blue",  "condition": "Factory New"},
            {"name": "MP5-SD | Phosphor",           "rarity": "Blue",  "condition": "Factory New"},
            {"name": "Nova | Toy Soldier",          "rarity": "Blue",  "condition": "Field-Tested"},
            {"name": "Sawed-Off | Devourer",        "rarity": "Blue",  "condition": "Minimal Wear"},
            {"name": "SCAR-20 | Enforcer",          "rarity": "Blue",  "condition": "Factory New"},
            {"name": "P2000 | Imperial Dragon",     "rarity": "Purple","condition": "Factory New"},
            {"name": "★ Navaja Knife",              "rarity": "Gold",  "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Navaja Knife | Fade",       "rarity": "Gold",  "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Navaja Knife | Crimson Web","rarity": "Gold",  "tier": "Legendary", "condition": "Factory New"},
        ]
    },
    "spectrum_2_case": {
        "name": "Spectrum 2 Case", "emoji": "🎳", "price": 2.5,
        "items": [
            {"name": "Dual Berettas | Metamorph",  "rarity": "Blue",  "condition": "Field-Tested"},
            {"name": "G3SG1 | Flux",               "rarity": "Blue",  "condition": "Factory New"},
            {"name": "MAC-10 | Aloha",             "rarity": "Blue",  "condition": "Minimal Wear"},
            {"name": "MP9 | Capillary",            "rarity": "Blue",  "condition": "Field-Tested"},
            {"name": "Nova | Gila",                "rarity": "Blue",  "condition": "Well-Worn"},
            {"name": "PP-Bizon | Azurite",         "rarity": "Blue",  "condition": "Factory New"},
            {"name": "SSG 08 | Fever Dream",       "rarity": "Blue",  "condition": "Minimal Wear"},
            {"name": "P250 | Hat Trick",           "rarity": "Purple","condition": "Factory New"},
            {"name": "★ Navaja Knife",             "rarity": "Gold",  "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Navaja Knife | Fade",      "rarity": "Gold",  "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Navaja Knife | Crimson Web","rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
        ]
    },
    "clutch_case": {
        "name": "Clutch Case", "emoji": "🎭", "price": 2.0,
        "items": [
            {"name": "CZ75-Auto | Emerald Quartz",  "rarity": "Blue",  "condition": "Minimal Wear"},
            {"name": "Five-SeveN | Angry Mob",      "rarity": "Blue",  "condition": "Minimal Wear"},
            {"name": "Galil AR | Cerberus",         "rarity": "Blue",  "condition": "Well-Worn"},
            {"name": "MP7 | Powercore",             "rarity": "Blue",  "condition": "Factory New"},
            {"name": "Nova | Wild Six",             "rarity": "Blue",  "condition": "Battle-Scarred"},
            {"name": "R8 Revolver | Survivalist",   "rarity": "Blue",  "condition": "Well-Worn"},
            {"name": "Sawed-Off | Limelight",       "rarity": "Blue",  "condition": "Field-Tested"},
            {"name": "MP5-SD | Phosphor",           "rarity": "Purple","condition": "Factory New"},
            {"name": "★ Shadow Daggers",            "rarity": "Gold",  "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Shadow Daggers | Fade",     "rarity": "Gold",  "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Shadow Daggers | Crimson Web","rarity": "Gold","tier": "Legendary", "condition": "Factory New"},
        ]
    },
    "horizon_case": {
        "name": "Horizon Case", "emoji": "🎪", "price": 2.0,
        "items": [
            {"name": "AK-47 | Neon Rider",         "rarity": "Blue",  "condition": "Factory New"},
            {"name": "CZ75-Auto | Eco",            "rarity": "Blue",  "condition": "Factory New"},
            {"name": "G3SG1 | High Seas",          "rarity": "Blue",  "condition": "Field-Tested"},
            {"name": "Galil AR | Cerberus",        "rarity": "Blue",  "condition": "Well-Worn"},
            {"name": "MP5-SD | Acid Wash",         "rarity": "Blue",  "condition": "Factory New"},
            {"name": "Sawed-Off | Morris",         "rarity": "Blue",  "condition": "Factory New"},
            {"name": "SCAR-20 | Bloodsport",       "rarity": "Blue",  "condition": "Factory New"},
            {"name": "P250 | Nevermore",           "rarity": "Purple","condition": "Factory New"},
            {"name": "★ Ursus Knife",              "rarity": "Gold",  "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Ursus Knife | Fade",       "rarity": "Gold",  "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Ursus Knife | Marble Fade","rarity": "Gold",  "tier": "Legendary", "condition": "Factory New"},
        ]
    },
    "danger_zone_case": {
        "name": "Danger Zone Case", "emoji": "🎯", "price": 2.0,
        "items": [
            {"name": "G3SG1 | Chronos",            "rarity": "Blue",  "condition": "Factory New"},
            {"name": "MP5-SD | Condition Zero",    "rarity": "Blue",  "condition": "Well-Worn"},
            {"name": "Nova | Toy Soldier",         "rarity": "Blue",  "condition": "Minimal Wear"},
            {"name": "P2000 | Lifted Spirits",     "rarity": "Blue",  "condition": "Factory New"},
            {"name": "SCAR-20 | Torn",             "rarity": "Blue",  "condition": "Field-Tested"},
            {"name": "SSG 08 | Death Strike",      "rarity": "Blue",  "condition": "Factory New"},
            {"name": "Tec-9 | Bamboozle",          "rarity": "Blue",  "condition": "Factory New"},
            {"name": "R8 Revolver | Grip",         "rarity": "Purple","condition": "Factory New"},
            {"name": "★ Paracord Knife",           "rarity": "Gold",  "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Paracord Knife | Fade",    "rarity": "Gold",  "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Paracord Knife | Slaughter","rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
        ]
    },
    "prisma_case": {
        "name": "Prisma Case", "emoji": "🎱", "price": 2.5,
        "items": [
            {"name": "FAMAS | Crypsis",            "rarity": "Blue",  "condition": "Well-Worn"},
            {"name": "AK-47 | Uncharted",          "rarity": "Blue",  "condition": "Well-Worn"},
            {"name": "MAC-10 | Whitefish",         "rarity": "Blue",  "condition": "Battle-Scarred"},
            {"name": "Galil AR | Akoben",          "rarity": "Blue",  "condition": "Minimal Wear"},
            {"name": "MP7 | Mischief",             "rarity": "Blue",  "condition": "Factory New"},
            {"name": "P250 | Verdigris",           "rarity": "Blue",  "condition": "Battle-Scarred"},
            {"name": "P90 | Off World",            "rarity": "Blue",  "condition": "Battle-Scarred"},
            {"name": "AWP | Atheris",              "rarity": "Purple","condition": "Factory New"},
            {"name": "★ Navaja Knife",             "rarity": "Gold",  "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Navaja Knife | Marble Fade","rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Navaja Knife | Tiger Tooth","rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
        ]
    },
    "shattered_web_case": {
        "name": "Shattered Web Case", "emoji": "🔫", "price": 4.0,
        "items": [
            {"name": "MP5-SD | Acid Wash",         "rarity": "Blue",  "condition": "Field-Tested"},
            {"name": "Nova | Plume",               "rarity": "Blue",  "condition": "Field-Tested"},
            {"name": "G3SG1 | Black Sand",         "rarity": "Blue",  "condition": "Field-Tested"},
            {"name": "R8 Revolver | Memento",      "rarity": "Blue",  "condition": "Field-Tested"},
            {"name": "Dual Berettas | Balance",    "rarity": "Blue",  "condition": "Well-Worn"},
            {"name": "SCAR-20 | Torn",             "rarity": "Blue",  "condition": "Well-Worn"},
            {"name": "M249 | Warbird",             "rarity": "Blue",  "condition": "Field-Tested"},
            {"name": "PP-Bizon | Embargo",         "rarity": "Purple","condition": "Minimal Wear"},
            {"name": "★ Nomad Knife",              "rarity": "Gold",  "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Nomad Knife | Fade",       "rarity": "Gold",  "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Nomad Knife | Crimson Web","rarity": "Gold",  "tier": "Legendary", "condition": "Factory New"},
        ]
    },
    "cs20_case": {
        "name": "CS20 Case", "emoji": "🌙", "price": 2.5,
        "items": [
            {"name": "Dual Berettas | Elite 1.6", "rarity": "Blue",  "condition": "Field-Tested"},
            {"name": "Tec-9 | Flash Out",         "rarity": "Blue",  "condition": "Field-Tested"},
            {"name": "MAC-10 | Classic Crate",    "rarity": "Blue",  "condition": "Well-Worn"},
            {"name": "MAG-7 | Popdog",            "rarity": "Blue",  "condition": "Factory New"},
            {"name": "SCAR-20 | Assault",         "rarity": "Blue",  "condition": "Minimal Wear"},
            {"name": "FAMAS | Decommissioned",    "rarity": "Blue",  "condition": "Well-Worn"},
            {"name": "Glock-18 | Sacrifice",      "rarity": "Blue",  "condition": "Factory New"},
            {"name": "M249 | Aztec",              "rarity": "Purple","condition": "Battle-Scarred"},
            {"name": "★ Classic Knife",           "rarity": "Gold",  "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Classic Knife | Fade",    "rarity": "Gold",  "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Classic Knife | Crimson Web","rarity": "Gold","tier": "Legendary", "condition": "Factory New"},
        ]
    },
    "prisma_2_case": {
        "name": "Prisma 2 Case", "emoji": "🎂", "price": 2.0,
        "items": [
            {"name": "AUG | Tom Cat",             "rarity": "Blue",  "condition": "Well-Worn"},
            {"name": "AWP | Capillary",           "rarity": "Blue",  "condition": "Field-Tested"},
            {"name": "CZ75-Auto | Distressed",    "rarity": "Blue",  "condition": "Factory New"},
            {"name": "Desert Eagle | Blue Ply",   "rarity": "Blue",  "condition": "Field-Tested"},
            {"name": "MP5-SD | Desert Strike",    "rarity": "Blue",  "condition": "Well-Worn"},
            {"name": "Negev | Prototype",         "rarity": "Blue",  "condition": "Minimal Wear"},
            {"name": "R8 Revolver | Bone Forged", "rarity": "Blue",  "condition": "Factory New"},
            {"name": "P2000 | Acid Etched",       "rarity": "Purple","condition": "Field-Tested"},
            {"name": "★ Navaja Knife",            "rarity": "Gold",  "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Navaja Knife | Marble Fade","rarity": "Gold","tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Navaja Knife | Tiger Tooth","rarity": "Gold","tier": "Legendary", "condition": "Factory New"},
        ]
    },
    "fracture_case": {
        "name": "Fracture Case", "emoji": "💎", "price": 2.0,
        "items": [
            {"name": "Negev | Ultralight",        "rarity": "Blue",  "condition": "Minimal Wear"},
            {"name": "P2000 | Gnarled",           "rarity": "Blue",  "condition": "Battle-Scarred"},
            {"name": "SG 553 | Ol' Rusty",        "rarity": "Blue",  "condition": "Field-Tested"},
            {"name": "SSG 08 | Mainframe 001",    "rarity": "Blue",  "condition": "Factory New"},
            {"name": "P250 | Cassette",           "rarity": "Blue",  "condition": "Minimal Wear"},
            {"name": "P90 | Freight",             "rarity": "Blue",  "condition": "Well-Worn"},
            {"name": "PP-Bizon | Runic",          "rarity": "Blue",  "condition": "Well-Worn"},
            {"name": "MAG-7 | Monster Call",      "rarity": "Purple","condition": "Well-Worn"},
            {"name": "★ Nomad Knife",             "rarity": "Gold",  "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Nomad Knife | Fade",      "rarity": "Gold",  "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Nomad Knife | Crimson Web","rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
        ]
    },
    "operation_broken_fang_case": {
        "name": "Operation Broken Fang Case", "emoji": "⚡", "price": 3.5,
        "items": [
            {"name": "CZ75-Auto | Vendetta",      "rarity": "Blue",  "condition": "Well-Worn"},
            {"name": "P90 | Cocoa Rampage",       "rarity": "Blue",  "condition": "Minimal Wear"},
            {"name": "G3SG1 | Digital Mesh",      "rarity": "Blue",  "condition": "Minimal Wear"},
            {"name": "Galil AR | Vandal",         "rarity": "Blue",  "condition": "Field-Tested"},
            {"name": "P250 | Contaminant",        "rarity": "Blue",  "condition": "Field-Tested"},
            {"name": "M249 | Deep Relief",        "rarity": "Blue",  "condition": "Field-Tested"},
            {"name": "MP5-SD | Condition Zero",   "rarity": "Blue",  "condition": "Field-Tested"},
            {"name": "AWP | Exoskeleton",         "rarity": "Purple","condition": "Factory New"},
            {"name": "★ Broken Fang Gloves | Yellow-banded","rarity": "Gold","tier": "Legendary","condition": "Factory New"},
            {"name": "★ Broken Fang Gloves | Unhinged",    "rarity": "Gold","tier": "Legendary","condition": "Factory New"},
            {"name": "★ Broken Fang Gloves | Needle Point","rarity": "Gold","tier": "Legendary","condition": "Factory New"},
        ]
    },
    "snakebite_case": {
        "name": "Snakebite Case", "emoji": "🌊", "price": 2.5,
        "items": [
            {"name": "SG 553 | Heavy Metal",      "rarity": "Blue",  "condition": "Field-Tested"},
            {"name": "Glock-18 | Clear Polymer",  "rarity": "Blue",  "condition": "Well-Worn"},
            {"name": "M249 | O.S.I.P.R.",         "rarity": "Blue",  "condition": "Factory New"},
            {"name": "CZ75-Auto | Circaetus",     "rarity": "Blue",  "condition": "Battle-Scarred"},
            {"name": "UMP-45 | Oscillator",       "rarity": "Blue",  "condition": "Factory New"},
            {"name": "R8 Revolver | Junk Yard",   "rarity": "Blue",  "condition": "Field-Tested"},
            {"name": "Nova | Windblown",           "rarity": "Blue",  "condition": "Well-Worn"},
            {"name": "P250 | Cyber Shell",        "rarity": "Purple","condition": "Well-Worn"},
            {"name": "★ Broken Fang Gloves | Yellow-banded","rarity": "Gold","tier": "Legendary","condition": "Factory New"},
            {"name": "★ Broken Fang Gloves | Unhinged",    "rarity": "Gold","tier": "Legendary","condition": "Factory New"},
            {"name": "★ Broken Fang Gloves | Needle Point","rarity": "Gold","tier": "Legendary","condition": "Factory New"},
        ]
    },
    "operation_riptide_case": {
        "name": "Operation Riptide Case", "emoji": "🌪️", "price": 3.0,
        "items": [
            {"name": "AUG | Plague",              "rarity": "Blue",  "condition": "Field-Tested"},
            {"name": "Dual Berettas | Tread",     "rarity": "Blue",  "condition": "Battle-Scarred"},
            {"name": "G3SG1 | Keeping Tabs",      "rarity": "Blue",  "condition": "Battle-Scarred"},
            {"name": "MP7 | Guerrilla",           "rarity": "Blue",  "condition": "Well-Worn"},
            {"name": "PP-Bizon | Lumen",          "rarity": "Blue",  "condition": "Factory New"},
            {"name": "USP-S | Black Lotus",       "rarity": "Blue",  "condition": "Well-Worn"},
            {"name": "XM1014 | Watchdog",         "rarity": "Blue",  "condition": "Well-Worn"},
            {"name": "MAG-7 | BI83 Spectrum",     "rarity": "Purple","condition": "Well-Worn"},
            {"name": "★ Bowie Knife | Gamma Doppler","rarity": "Gold","tier": "Legendary","condition": "Factory New"},
            {"name": "★ Bowie Knife | Gamma Doppler","rarity": "Gold","tier": "Legendary","condition": "Factory New"},
            {"name": "★ Bowie Knife | Gamma Doppler","rarity": "Gold","tier": "Legendary","condition": "Factory New"},
        ]
    },
    "dreams_and_nightmares_case": {
        "name": "Dreams & Nightmares Case", "emoji": "🎇", "price": 2.5,
        "items": [
            {"name": "Five-SeveN | Scrawl",       "rarity": "Blue",  "condition": "Field-Tested"},
            {"name": "MAC-10 | Ensnared",         "rarity": "Blue",  "condition": "Minimal Wear"},
            {"name": "MAG-7 | Foresight",         "rarity": "Blue",  "condition": "Well-Worn"},
            {"name": "MP5-SD | Necro Jr.",        "rarity": "Blue",  "condition": "Factory New"},
            {"name": "P2000 | Lifted Spirits",    "rarity": "Blue",  "condition": "Well-Worn"},
            {"name": "SCAR-20 | Poultrygeist",    "rarity": "Blue",  "condition": "Battle-Scarred"},
            {"name": "Sawed-Off | Spirit Board",  "rarity": "Blue",  "condition": "Battle-Scarred"},
            {"name": "PP-Bizon | Space Cat",      "rarity": "Purple","condition": "Factory New"},
            {"name": "★ Bowie Knife | Gamma Doppler","rarity": "Gold","tier": "Legendary","condition": "Factory New"},
            {"name": "★ Bowie Knife | Gamma Doppler","rarity": "Gold","tier": "Legendary","condition": "Factory New"},
            {"name": "★ Bowie Knife | Gamma Doppler","rarity": "Gold","tier": "Legendary","condition": "Factory New"},
        ]
    },
    "recoil_case": {
        "name": "Recoil Case", "emoji": "📦", "price": 2.0,
        "items": [
            {"name": "FAMAS | Meow 36",           "rarity": "Blue",  "condition": "Factory New"},
            {"name": "Galil AR | Destroyer",      "rarity": "Blue",  "condition": "Well-Worn"},
            {"name": "M4A4 | Poly Mag",           "rarity": "Blue",  "condition": "Battle-Scarred"},
            {"name": "MAC-10 | Monkeyflage",      "rarity": "Blue",  "condition": "Field-Tested"},
            {"name": "Negev | Drop Me",           "rarity": "Blue",  "condition": "Minimal Wear"},
            {"name": "UMP-45 | Roadblock",        "rarity": "Blue",  "condition": "Well-Worn"},
            {"name": "Glock-18 | Winterized",     "rarity": "Blue",  "condition": "Field-Tested"},
            {"name": "R8 Revolver | Crazy 8",     "rarity": "Purple","condition": "Well-Worn"},
            {"name": "★ Broken Fang Gloves | Yellow-banded","rarity": "Gold","tier": "Legendary","condition": "Factory New"},
            {"name": "★ Broken Fang Gloves | Unhinged",    "rarity": "Gold","tier": "Legendary","condition": "Factory New"},
            {"name": "★ Broken Fang Gloves | Needle Point","rarity": "Gold","tier": "Legendary","condition": "Factory New"},
        ]
    },
    "revolution_case": {
        "name": "Revolution Case", "emoji": "🎯", "price": 2.5,
        "items": [
            {"name": "MAG-7 | Insomnia",          "rarity": "Blue",  "condition": "Well-Worn"},
            {"name": "MP9 | Featherweight",       "rarity": "Blue",  "condition": "Battle-Scarred"},
            {"name": "SCAR-20 | Fragments",       "rarity": "Blue",  "condition": "Factory New"},
            {"name": "P250 | Re.built",           "rarity": "Blue",  "condition": "Minimal Wear"},
            {"name": "MP5-SD | Liquidation",      "rarity": "Blue",  "condition": "Battle-Scarred"},
            {"name": "SG 553 | Cyberforce",       "rarity": "Blue",  "condition": "Battle-Scarred"},
            {"name": "Tec-9 | Rebel",             "rarity": "Blue",  "condition": "Factory New"},
            {"name": "M4A1-S | Emphorosaur-S",    "rarity": "Purple","condition": "Factory New"},
            {"name": "★ Driver Gloves | Imperial Plaid","rarity": "Gold","tier": "Legendary","condition": "Factory New"},
            {"name": "★ Driver Gloves | King Snake",    "rarity": "Gold","tier": "Legendary","condition": "Factory New"},
            {"name": "★ Driver Gloves | Racing Green",  "rarity": "Gold","tier": "Legendary","condition": "Factory New"},
        ]
    },
    "kilowatt_case": {
        "name": "Kilowatt Case", "emoji": "⚡", "price": 3.5,
        "items": [
            {"name": "Dual Berettas | Hideout",   "rarity": "Blue",  "condition": "Minimal Wear"},
            {"name": "MAC-10 | Light Box",        "rarity": "Blue",  "condition": "Field-Tested"},
            {"name": "Nova | Dark Sigil",         "rarity": "Blue",  "condition": "Factory New"},
            {"name": "SSG 08 | Dezastre",         "rarity": "Blue",  "condition": "Minimal Wear"},
            {"name": "Tec-9 | Slag",              "rarity": "Blue",  "condition": "Minimal Wear"},
            {"name": "UMP-45 | Motorized",        "rarity": "Blue",  "condition": "Factory New"},
            {"name": "XM1014 | Irezumi",          "rarity": "Blue",  "condition": "Factory New"},
            {"name": "Glock-18 | Block-18",       "rarity": "Purple","condition": "Minimal Wear"},
            {"name": "★ Kukri Knife",             "rarity": "Gold",  "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Kukri Knife | Fade",      "rarity": "Gold",  "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Kukri Knife | Slaughter", "rarity": "Gold",  "tier": "Legendary", "condition": "Factory New"},
        ]
    },
    "gallery_case": {
        "name": "Gallery Case", "emoji": "🔥", "price": 3.0,
        "items": [
            {"name": "USP-S | 27",                "rarity": "Blue",  "condition": "Minimal Wear"},
            {"name": "Desert Eagle | Calligraffiti","rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "MP5-SD | Statics",          "rarity": "Blue",  "condition": "Factory New"},
            {"name": "AUG | Luxe Trim",           "rarity": "Blue",  "condition": "Field-Tested"},
            {"name": "M249 | Hypnosis",           "rarity": "Blue",  "condition": "Well-Worn"},
            {"name": "R8 Revolver | Tango",       "rarity": "Blue",  "condition": "Factory New"},
            {"name": "SCAR-20 | Trail Blazer",    "rarity": "Blue",  "condition": "Factory New"},
            {"name": "M4A4 | Turbine",            "rarity": "Purple","condition": "Factory New"},
            {"name": "★ Kukri Knife",             "rarity": "Gold",  "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Kukri Knife | Fade",      "rarity": "Gold",  "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Kukri Knife | Slaughter", "rarity": "Gold",  "tier": "Legendary", "condition": "Factory New"},
        ]
    },
    "fever_case": {
        "name": "Fever Case", "emoji": "💎", "price": 4.0,
        "items": [
            {"name": "M4A4 | Choppa",             "rarity": "Blue",  "condition": "Well-Worn"},
            {"name": "MAG-7 | Resupply",          "rarity": "Blue",  "condition": "Battle-Scarred"},
            {"name": "SSG 08 | Memorial",         "rarity": "Blue",  "condition": "Field-Tested"},
            {"name": "P2000 | Sure Grip",         "rarity": "Blue",  "condition": "Battle-Scarred"},
            {"name": "USP-S | PC-GRN",            "rarity": "Blue",  "condition": "Field-Tested"},
            {"name": "MP9 | Nexus",               "rarity": "Blue",  "condition": "Minimal Wear"},
            {"name": "XM1014 | Mockingbird",      "rarity": "Blue",  "condition": "Factory New"},
            {"name": "Desert Eagle | Serpent Strike","rarity": "Purple","condition": "Well-Worn"},
            {"name": "★ Survival Knife",               "rarity": "Gold","tier": "Legendary","condition": "Factory New"},
            {"name": "★ Survival Knife | Marble Fade", "rarity": "Gold","tier": "Legendary","condition": "Factory New"},
            {"name": "★ Survival Knife | Tiger Tooth", "rarity": "Gold","tier": "Legendary","condition": "Factory New"},
        ]
    },
}

# ============================================================
# CONTAINER IMAGE MAPPING (by case name)
# ============================================================
import os
import re
import json

CONTAINERS_JSON_PATH = os.path.join(os.path.dirname(__file__), "containers.json")

def build_container_image_map() -> Dict[str, str]:
    """
    Build mapping from our case_id (e.g., "cs:go_weapon_case") 
    to the container image filename (e.g., "172.webp") by matching the case name.
    """
    if not os.path.exists(CONTAINERS_JSON_PATH):
        print(f"⚠️ {CONTAINERS_JSON_PATH} not found – container images will fallback")
        return {}

    with open(CONTAINERS_JSON_PATH, "r", encoding="utf-8") as f:
        containers = json.load(f)

    # Build dict: normalized name -> filename
    container_by_name = {}
    for entry in containers:
        name = entry.get("name")
        image = entry.get("containerImage")
        if name and image:
            normalized = " ".join(name.lower().split())   # normalize whitespace & case
            filename = os.path.basename(image)            # "172.webp"
            container_by_name[normalized] = filename

    # Map our case IDs by matching names
    mapping = {}
    for case_id, case_data in CASES.items():
        case_name = case_data.get("name")
        if not case_name:
            continue
        normalized_case = " ".join(case_name.lower().split())
        if normalized_case in container_by_name:
            mapping[case_id] = container_by_name[normalized_case]
        else:
            print(f"⚠️ No container image found for case: {case_name} (id: {case_id})")

    return mapping

# Build the global map
CONTAINER_IMAGE_MAP = build_container_image_map()

SKINS_JSON_PATH = os.path.join(os.path.dirname(__file__), "skins.json")

def load_skin_name_to_image():
    if not os.path.exists(SKINS_JSON_PATH):
        print(f"⚠️ {SKINS_JSON_PATH} not found – skin images will fallback to default")
        return {}
    with open(SKINS_JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    name_to_image = {}
    for entry in data:
        skin_name = entry.get("name")
        skin_image = entry.get("skinImage")
        if skin_name and skin_image:
            filename = os.path.basename(skin_image)
            # Keep the first occurrence; you may want to keep the latest one
            if skin_name not in name_to_image:
                name_to_image[skin_name] = filename
    return name_to_image

SKIN_NAME_TO_IMAGE = load_skin_name_to_image()

def get_skin_image_filename(item_name: str) -> str:
    if not SKIN_NAME_TO_IMAGE:
        return None

    # Remove StatTrak, ★, and any trailing condition in parentheses
    clean = re.sub(r'StatTrak™\s*|★\s*', '', item_name).strip()
    clean = re.sub(r'\s*\([^)]*\)$', '', clean).strip()
    clean = re.sub(r'^[⭐🔴💗🟪🟦]\s*', '', clean)
    # Extract the skin part (everything after the last '|')
    if ' | ' in clean:
        skin = clean.split(' | ')[-1].strip()
    else:
        skin = clean

    # Try full item name first (e.g. "AK-47 | Redline")
    if clean in SKIN_NAME_TO_IMAGE:
        return SKIN_NAME_TO_IMAGE[clean]

    # Direct match on skin part
    if skin in SKIN_NAME_TO_IMAGE:
        return SKIN_NAME_TO_IMAGE[skin]

    # Case-insensitive match
    skin_lower = skin.lower()
    for key, filename in SKIN_NAME_TO_IMAGE.items():
        if key.lower() == skin_lower:
            return filename

    # Partial match (e.g., "Gamma Doppler Phase 2" -> "Gamma Doppler")
    for key in SKIN_NAME_TO_IMAGE:
        if key in skin or skin in key:
            return SKIN_NAME_TO_IMAGE[key]

    return None

# ============================================================
# STICKER CAPSULES
# ============================================================

STICKER_CAPSULES = {
    "cs20_sticker_capsule": {
        "name": "CS20 Sticker Capsule",
        "emoji": "\ud83c\udf82",
        "price": 1.0,
        "image": "assets/containers/2103.webp",
        "stickers": [{"name": "CS20 Classic (Holo)", "rarity": "👑 Rare", "image": "assets/stickers/4513.webp"}, {"name": "Too Old for This", "rarity": "💫", "image": "assets/stickers/4514.webp"}, {"name": "Pixel Avenger", "rarity": "💫", "image": "assets/stickers/4515.webp"}, {"name": "Aztec", "rarity": "💫", "image": "assets/stickers/4516.webp"}, {"name": "Too Late", "rarity": "💫", "image": "assets/stickers/4517.webp"}, {"name": "Friend Code", "rarity": "💫", "image": "assets/stickers/4518.webp"}, {"name": "Clutchman (Holo)", "rarity": "👑 Rare", "image": "assets/stickers/4519.webp"}, {"name": "All Hail the King (Foil)", "rarity": "🔥", "image": "assets/stickers/4520.webp"}, {"name": "Door Stuck (Foil)", "rarity": "🔥", "image": "assets/stickers/4521.webp"}, {"name": "Dragon Lore (Foil)", "rarity": "🔥", "image": "assets/stickers/4522.webp"}, {"name": "Guinea Pig (Holo)", "rarity": "👑 Rare", "image": "assets/stickers/4523.webp"}, {"name": "Obey SAS", "rarity": "💫", "image": "assets/stickers/4524.webp"}, {"name": "Fire in the Hole (Holo)", "rarity": "👑 Rare", "image": "assets/stickers/4525.webp"}, {"name": "Nuke Beast", "rarity": "💫", "image": "assets/stickers/4526.webp"}, {"name": "Mondays", "rarity": "💫", "image": "assets/stickers/4527.webp"}, {"name": "Boost (Holo)", "rarity": "👑 Rare", "image": "assets/stickers/4528.webp"}, {"name": "Rush 4x20 (Holo)", "rarity": "👑 Rare", "image": "assets/stickers/4529.webp"}, {"name": "Separate Pixels", "rarity": "💫", "image": "assets/stickers/4530.webp"}, {"name": "Surf's Up", "rarity": "💫", "image": "assets/stickers/4531.webp"}, {"name": "Temperance", "rarity": "💫", "image": "assets/stickers/4532.webp"}],
    },
    "recoil_sticker_collection": {
        "name": "Recoil Sticker Collection",
        "emoji": "\u2b50",
        "price": 0.5,
        "image": "assets/containers/2221.webp",
        "stickers": [{"name": "Hello AK-47", "rarity": "💫", "image": "assets/stickers/4649.webp"}, {"name": "Hello AK-47 (Gold)", "rarity": "👑 Rare", "image": "assets/stickers/4650.webp"}, {"name": "Hello AUG", "rarity": "💫", "image": "assets/stickers/4651.webp"}, {"name": "Hello AUG (Gold)", "rarity": "👑 Rare", "image": "assets/stickers/4652.webp"}, {"name": "Hello AWP", "rarity": "💫", "image": "assets/stickers/4653.webp"}, {"name": "Hello AWP (Gold)", "rarity": "👑 Rare", "image": "assets/stickers/4654.webp"}, {"name": "Hello PP-Bizon", "rarity": "💫", "image": "assets/stickers/4655.webp"}, {"name": "Hello PP-Bizon (Gold)", "rarity": "👑 Rare", "image": "assets/stickers/4656.webp"}, {"name": "Hello CZ75-Auto", "rarity": "💫", "image": "assets/stickers/4657.webp"}, {"name": "Hello CZ75-Auto (Gold)", "rarity": "👑 Rare", "image": "assets/stickers/4658.webp"}, {"name": "Hello FAMAS", "rarity": "💫", "image": "assets/stickers/4659.webp"}, {"name": "Hello FAMAS (Gold)", "rarity": "👑 Rare", "image": "assets/stickers/4660.webp"}, {"name": "Hello Galil AR", "rarity": "💫", "image": "assets/stickers/4661.webp"}, {"name": "Hello Galil AR (Gold)", "rarity": "👑 Rare", "image": "assets/stickers/4662.webp"}, {"name": "Hello M4A1-S", "rarity": "💫", "image": "assets/stickers/4663.webp"}, {"name": "Hello M4A1-S (Gold)", "rarity": "👑 Rare", "image": "assets/stickers/4664.webp"}, {"name": "Hello M4A4", "rarity": "💫", "image": "assets/stickers/4665.webp"}, {"name": "Hello M4A4 (Gold)", "rarity": "👑 Rare", "image": "assets/stickers/4666.webp"}, {"name": "Hello MAC-10", "rarity": "💫", "image": "assets/stickers/4667.webp"}, {"name": "Hello MAC-10 (Gold)", "rarity": "👑 Rare", "image": "assets/stickers/4668.webp"}, {"name": "Hello MP7", "rarity": "💫", "image": "assets/stickers/4669.webp"}, {"name": "Hello MP7 (Gold)", "rarity": "👑 Rare", "image": "assets/stickers/4670.webp"}, {"name": "Hello MP9", "rarity": "💫", "image": "assets/stickers/4671.webp"}, {"name": "Hello MP9 (Gold)", "rarity": "👑 Rare", "image": "assets/stickers/4672.webp"}, {"name": "Hello P90", "rarity": "💫", "image": "assets/stickers/4673.webp"}, {"name": "Hello P90 (Gold)", "rarity": "👑 Rare", "image": "assets/stickers/4674.webp"}, {"name": "Hello SG 553", "rarity": "💫", "image": "assets/stickers/4675.webp"}, {"name": "Hello SG 553 (Gold)", "rarity": "👑 Rare", "image": "assets/stickers/4676.webp"}, {"name": "Hello UMP-45", "rarity": "💫", "image": "assets/stickers/4677.webp"}, {"name": "Hello UMP-45 (Gold)", "rarity": "👑 Rare", "image": "assets/stickers/4678.webp"}, {"name": "Hello XM1014", "rarity": "💫", "image": "assets/stickers/4679.webp"}, {"name": "Hello XM1014 (Gold)", "rarity": "👑 Rare", "image": "assets/stickers/4680.webp"}],
    },
    "austin_2025_champions_autograp": {
        "name": "Austin 2025 Champions Autograph",
        "emoji": "\ud83c\udfc6",
        "price": 5.0,
        "image": "assets/containers/1989.webp",
        "stickers": [{"name": "apEX (Champion) | Austin 2025", "rarity": "💫", "image": "assets/stickers/9431.webp"}, {"name": "apEX (Foil, Champion) | Austin 2025", "rarity": "👑 Rare", "image": "assets/stickers/9432.webp"}, {"name": "apEX (Holo, Champion) | Austin 2025", "rarity": "🔥", "image": "assets/stickers/9433.webp"}, {"name": "apEX (Gold, Champion) | Austin 2025", "rarity": "👑 Legendary", "image": "assets/stickers/9434.webp"}, {"name": "ZywOo (Champion) | Austin 2025", "rarity": "💫", "image": "assets/stickers/9435.webp"}, {"name": "ZywOo (Foil, Champion) | Austin 2025", "rarity": "👑 Rare", "image": "assets/stickers/9436.webp"}, {"name": "ZywOo (Holo, Champion) | Austin 2025", "rarity": "🔥", "image": "assets/stickers/9437.webp"}, {"name": "ZywOo (Gold, Champion) | Austin 2025", "rarity": "👑 Legendary", "image": "assets/stickers/9438.webp"}, {"name": "FlameZ (Champion) | Austin 2025", "rarity": "💫", "image": "assets/stickers/9439.webp"}, {"name": "FlameZ (Foil, Champion) | Austin 2025", "rarity": "👑 Rare", "image": "assets/stickers/9440.webp"}, {"name": "FlameZ (Holo, Champion) | Austin 2025", "rarity": "🔥", "image": "assets/stickers/9441.webp"}, {"name": "FlameZ (Gold, Champion) | Austin 2025", "rarity": "👑 Legendary", "image": "assets/stickers/9442.webp"}, {"name": "mezii (Champion) | Austin 2025", "rarity": "💫", "image": "assets/stickers/9443.webp"}, {"name": "mezii (Foil, Champion) | Austin 2025", "rarity": "👑 Rare", "image": "assets/stickers/9444.webp"}, {"name": "mezii (Holo, Champion) | Austin 2025", "rarity": "🔥", "image": "assets/stickers/9445.webp"}, {"name": "mezii (Gold, Champion) | Austin 2025", "rarity": "👑 Legendary", "image": "assets/stickers/9446.webp"}, {"name": "ropz (Champion) | Austin 2025", "rarity": "💫", "image": "assets/stickers/9447.webp"}, {"name": "ropz (Foil, Champion) | Austin 2025", "rarity": "👑 Rare", "image": "assets/stickers/9448.webp"}, {"name": "ropz (Holo, Champion) | Austin 2025", "rarity": "🔥", "image": "assets/stickers/9449.webp"}, {"name": "ropz (Gold, Champion) | Austin 2025", "rarity": "👑 Legendary", "image": "assets/stickers/9450.webp"}],
    },
    "budapest_2025_champions_autogr": {
        "name": "Budapest 2025 Champions Autograph",
        "emoji": "\ud83c\udfc6",
        "price": 5.0,
        "image": "assets/containers/2098.webp",
        "stickers": [{"name": "apEX (Champion) | Budapest 2025", "rarity": "💫", "image": "assets/stickers/10294.webp"}, {"name": "apEX (Embroidered, Champion) | Budapest 2025", "rarity": "👑 Rare", "image": "assets/stickers/10295.webp"}, {"name": "apEX (Holo, Champion) | Budapest 2025", "rarity": "🔥", "image": "assets/stickers/10296.webp"}, {"name": "apEX (Gold, Champion) | Budapest 2025", "rarity": "👑 Legendary", "image": "assets/stickers/10297.webp"}, {"name": "FlameZ (Champion) | Budapest 2025", "rarity": "💫", "image": "assets/stickers/10298.webp"}, {"name": "FlameZ (Embroidered, Champion) | Budapest 2025", "rarity": "👑 Rare", "image": "assets/stickers/10299.webp"}, {"name": "FlameZ (Holo, Champion) | Budapest 2025", "rarity": "🔥", "image": "assets/stickers/10300.webp"}, {"name": "FlameZ (Gold, Champion) | Budapest 2025", "rarity": "👑 Legendary", "image": "assets/stickers/10301.webp"}, {"name": "mezii (Champion) | Budapest 2025", "rarity": "💫", "image": "assets/stickers/10302.webp"}, {"name": "mezii (Embroidered, Champion) | Budapest 2025", "rarity": "👑 Rare", "image": "assets/stickers/10303.webp"}, {"name": "mezii (Holo, Champion) | Budapest 2025", "rarity": "🔥", "image": "assets/stickers/10304.webp"}, {"name": "mezii (Gold, Champion) | Budapest 2025", "rarity": "👑 Legendary", "image": "assets/stickers/10305.webp"}, {"name": "ropz (Champion) | Budapest 2025", "rarity": "💫", "image": "assets/stickers/10306.webp"}, {"name": "ropz (Embroidered, Champion) | Budapest 2025", "rarity": "👑 Rare", "image": "assets/stickers/10307.webp"}, {"name": "ropz (Holo, Champion) | Budapest 2025", "rarity": "🔥", "image": "assets/stickers/10308.webp"}, {"name": "ropz (Gold, Champion) | Budapest 2025", "rarity": "👑 Legendary", "image": "assets/stickers/10309.webp"}, {"name": "ZywOo (Champion) | Budapest 2025", "rarity": "💫", "image": "assets/stickers/10310.webp"}, {"name": "ZywOo (Embroidered, Champion) | Budapest 2025", "rarity": "👑 Rare", "image": "assets/stickers/10311.webp"}, {"name": "ZywOo (Holo, Champion) | Budapest 2025", "rarity": "🔥", "image": "assets/stickers/10312.webp"}, {"name": "ZywOo (Gold, Champion) | Budapest 2025", "rarity": "👑 Legendary", "image": "assets/stickers/10313.webp"}],
    },
    "copenhagen_2024_champions_auto": {
        "name": "Copenhagen 2024 Champions Autograph",
        "emoji": "\ud83c\udfc6",
        "price": 4.0,
        "image": "assets/containers/2112.webp",
        "stickers": [{"name": "jL (Champion) | Copenhagen 2024", "rarity": "💫", "image": "assets/stickers/7859.webp"}, {"name": "jL (Glitter, Champion) | Copenhagen 2024", "rarity": "👑 Rare", "image": "assets/stickers/7860.webp"}, {"name": "jL (Holo, Champion) | Copenhagen 2024", "rarity": "🔥", "image": "assets/stickers/7861.webp"}, {"name": "jL (Gold, Champion) | Copenhagen 2024", "rarity": "👑 Legendary", "image": "assets/stickers/7862.webp"}, {"name": "Aleksib (Champion) | Copenhagen 2024", "rarity": "💫", "image": "assets/stickers/7863.webp"}, {"name": "Aleksib (Glitter, Champion) | Copenhagen 2024", "rarity": "👑 Rare", "image": "assets/stickers/7864.webp"}, {"name": "Aleksib (Holo, Champion) | Copenhagen 2024", "rarity": "🔥", "image": "assets/stickers/7865.webp"}, {"name": "Aleksib (Gold, Champion) | Copenhagen 2024", "rarity": "👑 Legendary", "image": "assets/stickers/7866.webp"}, {"name": "b1t (Champion) | Copenhagen 2024", "rarity": "💫", "image": "assets/stickers/7867.webp"}, {"name": "b1t (Glitter, Champion) | Copenhagen 2024", "rarity": "👑 Rare", "image": "assets/stickers/7868.webp"}, {"name": "b1t (Holo, Champion) | Copenhagen 2024", "rarity": "🔥", "image": "assets/stickers/7869.webp"}, {"name": "b1t (Gold, Champion) | Copenhagen 2024", "rarity": "👑 Legendary", "image": "assets/stickers/7870.webp"}, {"name": "iM (Champion) | Copenhagen 2024", "rarity": "💫", "image": "assets/stickers/7871.webp"}, {"name": "iM (Glitter, Champion) | Copenhagen 2024", "rarity": "👑 Rare", "image": "assets/stickers/7872.webp"}, {"name": "iM (Holo, Champion) | Copenhagen 2024", "rarity": "🔥", "image": "assets/stickers/7873.webp"}, {"name": "iM (Gold, Champion) | Copenhagen 2024", "rarity": "👑 Legendary", "image": "assets/stickers/7874.webp"}, {"name": "w0nderful (Champion) | Copenhagen 2024", "rarity": "💫", "image": "assets/stickers/7875.webp"}, {"name": "w0nderful (Glitter, Champion) | Copenhagen 2024", "rarity": "👑 Rare", "image": "assets/stickers/7876.webp"}, {"name": "w0nderful (Holo, Champion) | Copenhagen 2024", "rarity": "🔥", "image": "assets/stickers/7877.webp"}, {"name": "w0nderful (Gold, Champion) | Copenhagen 2024", "rarity": "👑 Legendary", "image": "assets/stickers/7878.webp"}],
    },
    "shanghai_2024_champions_autogr": {
        "name": "Shanghai 2024 Champions Autograph",
        "emoji": "\ud83c\udfc6",
        "price": 4.0,
        "image": "assets/containers/2156.webp",
        "stickers": [{"name": "chopper (Champion) | Shanghai 2024", "rarity": "💫", "image": "assets/stickers/8533.webp"}, {"name": "chopper (Glitter, Champion) | Shanghai 2024", "rarity": "👑 Rare", "image": "assets/stickers/8534.webp"}, {"name": "chopper (Holo, Champion) | Shanghai 2024", "rarity": "🔥", "image": "assets/stickers/8535.webp"}, {"name": "chopper (Gold, Champion) | Shanghai 2024", "rarity": "👑 Legendary", "image": "assets/stickers/8536.webp"}, {"name": "magixx (Champion) | Shanghai 2024", "rarity": "💫", "image": "assets/stickers/8537.webp"}, {"name": "magixx (Glitter, Champion) | Shanghai 2024", "rarity": "👑 Rare", "image": "assets/stickers/8538.webp"}, {"name": "magixx (Holo, Champion) | Shanghai 2024", "rarity": "🔥", "image": "assets/stickers/8539.webp"}, {"name": "magixx (Gold, Champion) | Shanghai 2024", "rarity": "👑 Legendary", "image": "assets/stickers/8540.webp"}, {"name": "donk (Champion) | Shanghai 2024", "rarity": "💫", "image": "assets/stickers/8541.webp"}, {"name": "donk (Glitter, Champion) | Shanghai 2024", "rarity": "👑 Rare", "image": "assets/stickers/8542.webp"}, {"name": "donk (Holo, Champion) | Shanghai 2024", "rarity": "🔥", "image": "assets/stickers/8543.webp"}, {"name": "donk (Gold, Champion) | Shanghai 2024", "rarity": "👑 Legendary", "image": "assets/stickers/8544.webp"}, {"name": "sh1ro (Champion) | Shanghai 2024", "rarity": "💫", "image": "assets/stickers/8545.webp"}, {"name": "sh1ro (Glitter, Champion) | Shanghai 2024", "rarity": "👑 Rare", "image": "assets/stickers/8546.webp"}, {"name": "sh1ro (Holo, Champion) | Shanghai 2024", "rarity": "🔥", "image": "assets/stickers/8547.webp"}, {"name": "sh1ro (Gold, Champion) | Shanghai 2024", "rarity": "👑 Legendary", "image": "assets/stickers/8548.webp"}, {"name": "zont1x (Champion) | Shanghai 2024", "rarity": "💫", "image": "assets/stickers/8549.webp"}, {"name": "zont1x (Glitter, Champion) | Shanghai 2024", "rarity": "👑 Rare", "image": "assets/stickers/8550.webp"}, {"name": "zont1x (Holo, Champion) | Shanghai 2024", "rarity": "🔥", "image": "assets/stickers/8551.webp"}, {"name": "zont1x (Gold, Champion) | Shanghai 2024", "rarity": "👑 Legendary", "image": "assets/stickers/8552.webp"}],
    },
    "paris_2023_champions_autograph": {
        "name": "Paris 2023 Champions Autograph",
        "emoji": "\ud83c\udfc6",
        "price": 3.0,
        "image": "assets/containers/2138.webp",
        "stickers": [{"name": "apEX (Champion) | Paris 2023", "rarity": "💫", "image": "assets/stickers/7213.webp"}, {"name": "apEX (Glitter, Champion) | Paris 2023", "rarity": "👑 Rare", "image": "assets/stickers/7214.webp"}, {"name": "apEX (Holo, Champion) | Paris 2023", "rarity": "🔥", "image": "assets/stickers/7215.webp"}, {"name": "apEX (Gold, Champion) | Paris 2023", "rarity": "👑 Legendary", "image": "assets/stickers/7216.webp"}, {"name": "dupreeh (Champion) | Paris 2023", "rarity": "💫", "image": "assets/stickers/7217.webp"}, {"name": "dupreeh (Glitter, Champion) | Paris 2023", "rarity": "👑 Rare", "image": "assets/stickers/7218.webp"}, {"name": "dupreeh (Holo, Champion) | Paris 2023", "rarity": "🔥", "image": "assets/stickers/7219.webp"}, {"name": "dupreeh (Gold, Champion) | Paris 2023", "rarity": "👑 Legendary", "image": "assets/stickers/7220.webp"}, {"name": "Magisk (Champion) | Paris 2023", "rarity": "💫", "image": "assets/stickers/7221.webp"}, {"name": "Magisk (Glitter, Champion) | Paris 2023", "rarity": "👑 Rare", "image": "assets/stickers/7222.webp"}, {"name": "Magisk (Holo, Champion) | Paris 2023", "rarity": "🔥", "image": "assets/stickers/7223.webp"}, {"name": "Magisk (Gold, Champion) | Paris 2023", "rarity": "👑 Legendary", "image": "assets/stickers/7224.webp"}, {"name": "Spinx (Champion) | Paris 2023", "rarity": "💫", "image": "assets/stickers/7225.webp"}, {"name": "Spinx (Glitter, Champion) | Paris 2023", "rarity": "👑 Rare", "image": "assets/stickers/7226.webp"}, {"name": "Spinx (Holo, Champion) | Paris 2023", "rarity": "🔥", "image": "assets/stickers/7227.webp"}, {"name": "Spinx (Gold, Champion) | Paris 2023", "rarity": "👑 Legendary", "image": "assets/stickers/7228.webp"}, {"name": "ZywOo (Champion) | Paris 2023", "rarity": "💫", "image": "assets/stickers/7229.webp"}, {"name": "ZywOo (Glitter, Champion) | Paris 2023", "rarity": "👑 Rare", "image": "assets/stickers/7230.webp"}, {"name": "ZywOo (Holo, Champion) | Paris 2023", "rarity": "🔥", "image": "assets/stickers/7231.webp"}, {"name": "ZywOo (Gold, Champion) | Paris 2023", "rarity": "👑 Legendary", "image": "assets/stickers/7232.webp"}],
    },
    "rio_2022_champions_autograph": {
        "name": "Rio 2022 Champions Autograph",
        "emoji": "\ud83c\udfc6",
        "price": 2.5,
        "image": "assets/containers/2149.webp",
        "stickers": [{"name": "FL1T (Champion) | Rio 2022", "rarity": "💫", "image": "assets/stickers/6566.webp"}, {"name": "FL1T (Glitter, Champion) | Rio 2022", "rarity": "👑 Rare", "image": "assets/stickers/6567.webp"}, {"name": "FL1T (Holo, Champion) | Rio 2022", "rarity": "🔥", "image": "assets/stickers/6568.webp"}, {"name": "FL1T (Gold, Champion) | Rio 2022", "rarity": "👑 Legendary", "image": "assets/stickers/6569.webp"}, {"name": "n0rb3r7 (Champion) | Rio 2022", "rarity": "💫", "image": "assets/stickers/6570.webp"}, {"name": "n0rb3r7 (Glitter, Champion) | Rio 2022", "rarity": "👑 Rare", "image": "assets/stickers/6571.webp"}, {"name": "n0rb3r7 (Holo, Champion) | Rio 2022", "rarity": "🔥", "image": "assets/stickers/6572.webp"}, {"name": "n0rb3r7 (Gold, Champion) | Rio 2022", "rarity": "👑 Legendary", "image": "assets/stickers/6573.webp"}, {"name": "Jame (Champion) | Rio 2022", "rarity": "💫", "image": "assets/stickers/6574.webp"}, {"name": "Jame (Glitter, Champion) | Rio 2022", "rarity": "👑 Rare", "image": "assets/stickers/6575.webp"}, {"name": "Jame (Holo, Champion) | Rio 2022", "rarity": "🔥", "image": "assets/stickers/6576.webp"}, {"name": "Jame (Gold, Champion) | Rio 2022", "rarity": "👑 Legendary", "image": "assets/stickers/6577.webp"}, {"name": "qikert (Champion) | Rio 2022", "rarity": "💫", "image": "assets/stickers/6578.webp"}, {"name": "qikert (Glitter, Champion) | Rio 2022", "rarity": "👑 Rare", "image": "assets/stickers/6579.webp"}, {"name": "qikert (Holo, Champion) | Rio 2022", "rarity": "🔥", "image": "assets/stickers/6580.webp"}, {"name": "qikert (Gold, Champion) | Rio 2022", "rarity": "👑 Legendary", "image": "assets/stickers/6581.webp"}, {"name": "fame (Champion) | Rio 2022", "rarity": "💫", "image": "assets/stickers/6582.webp"}, {"name": "fame (Glitter, Champion) | Rio 2022", "rarity": "👑 Rare", "image": "assets/stickers/6583.webp"}, {"name": "fame (Holo, Champion) | Rio 2022", "rarity": "🔥", "image": "assets/stickers/6584.webp"}, {"name": "fame (Gold, Champion) | Rio 2022", "rarity": "👑 Legendary", "image": "assets/stickers/6585.webp"}],
    },
    "antwerp_2022_champions_autogra": {
        "name": "Antwerp 2022 Champions Autograph",
        "emoji": "\ud83c\udfc6",
        "price": 2.5,
        "image": "assets/containers/1982.webp",
        "stickers": [{"name": "rain (Champion) | Antwerp 2022", "rarity": "💫", "image": "assets/stickers/5876.webp"}, {"name": "rain (Glitter, Champion) | Antwerp 2022", "rarity": "👑 Rare", "image": "assets/stickers/5877.webp"}, {"name": "rain (Holo, Champion) | Antwerp 2022", "rarity": "🔥", "image": "assets/stickers/5878.webp"}, {"name": "rain (Gold, Champion) | Antwerp 2022", "rarity": "👑 Legendary", "image": "assets/stickers/5879.webp"}, {"name": "karrigan (Champion) | Antwerp 2022", "rarity": "💫", "image": "assets/stickers/5880.webp"}, {"name": "karrigan (Glitter, Champion) | Antwerp 2022", "rarity": "👑 Rare", "image": "assets/stickers/5881.webp"}, {"name": "karrigan (Holo, Champion) | Antwerp 2022", "rarity": "🔥", "image": "assets/stickers/5882.webp"}, {"name": "karrigan (Gold, Champion) | Antwerp 2022", "rarity": "👑 Legendary", "image": "assets/stickers/5883.webp"}, {"name": "Twistzz (Champion) | Antwerp 2022", "rarity": "💫", "image": "assets/stickers/5884.webp"}, {"name": "Twistzz (Glitter, Champion) | Antwerp 2022", "rarity": "👑 Rare", "image": "assets/stickers/5885.webp"}, {"name": "Twistzz (Holo, Champion) | Antwerp 2022", "rarity": "🔥", "image": "assets/stickers/5886.webp"}, {"name": "Twistzz (Gold, Champion) | Antwerp 2022", "rarity": "👑 Legendary", "image": "assets/stickers/5887.webp"}, {"name": "broky (Champion) | Antwerp 2022", "rarity": "💫", "image": "assets/stickers/5888.webp"}, {"name": "broky (Glitter, Champion) | Antwerp 2022", "rarity": "👑 Rare", "image": "assets/stickers/5889.webp"}, {"name": "broky (Holo, Champion) | Antwerp 2022", "rarity": "🔥", "image": "assets/stickers/5890.webp"}, {"name": "broky (Gold, Champion) | Antwerp 2022", "rarity": "👑 Legendary", "image": "assets/stickers/5891.webp"}, {"name": "ropz (Champion) | Antwerp 2022", "rarity": "💫", "image": "assets/stickers/5892.webp"}, {"name": "ropz (Glitter, Champion) | Antwerp 2022", "rarity": "👑 Rare", "image": "assets/stickers/5893.webp"}, {"name": "ropz (Holo, Champion) | Antwerp 2022", "rarity": "🔥", "image": "assets/stickers/5894.webp"}, {"name": "ropz (Gold, Champion) | Antwerp 2022", "rarity": "👑 Legendary", "image": "assets/stickers/5895.webp"}],
    },
    "stockholm_2021_champions_autog": {
        "name": "Stockholm 2021 Champions Autograph",
        "emoji": "\ud83c\udfc6",
        "price": 2.0,
        "image": "assets/containers/2173.webp",
        "stickers": [{"name": "s1mple | Stockholm 2021", "rarity": "💫", "image": "assets/stickers/5129.webp"}, {"name": "s1mple (Holo) | Stockholm 2021", "rarity": "👑 Rare", "image": "assets/stickers/5130.webp"}, {"name": "s1mple (Gold) | Stockholm 2021", "rarity": "👑 Legendary", "image": "assets/stickers/5131.webp"}, {"name": "Perfecto | Stockholm 2021", "rarity": "💫", "image": "assets/stickers/5132.webp"}, {"name": "Perfecto (Holo) | Stockholm 2021", "rarity": "👑 Rare", "image": "assets/stickers/5133.webp"}, {"name": "Perfecto (Gold) | Stockholm 2021", "rarity": "👑 Legendary", "image": "assets/stickers/5134.webp"}, {"name": "Boombl4 | Stockholm 2021", "rarity": "💫", "image": "assets/stickers/5135.webp"}, {"name": "Boombl4 (Holo) | Stockholm 2021", "rarity": "👑 Rare", "image": "assets/stickers/5136.webp"}, {"name": "Boombl4 (Gold) | Stockholm 2021", "rarity": "👑 Legendary", "image": "assets/stickers/5137.webp"}, {"name": "b1t | Stockholm 2021", "rarity": "💫", "image": "assets/stickers/5138.webp"}, {"name": "b1t (Holo) | Stockholm 2021", "rarity": "👑 Rare", "image": "assets/stickers/5139.webp"}, {"name": "b1t (Gold) | Stockholm 2021", "rarity": "👑 Legendary", "image": "assets/stickers/5140.webp"}, {"name": "electroNic | Stockholm 2021", "rarity": "💫", "image": "assets/stickers/5141.webp"}, {"name": "electroNic (Holo) | Stockholm 2021", "rarity": "👑 Rare", "image": "assets/stickers/5142.webp"}, {"name": "electroNic (Gold) | Stockholm 2021", "rarity": "👑 Legendary", "image": "assets/stickers/5143.webp"}],
    },
    "boston_2018_legends_autograph": {
        "name": "Boston 2018 Legends Autograph",
        "emoji": "\ud83d\udd25",
        "price": 1.5,
        "image": "assets/containers/2092.webp",
        "stickers": [{"name": "AdreN | Boston 2018", "rarity": "💫", "image": "assets/stickers/2561.webp"}, {"name": "AdreN (Foil) | Boston 2018", "rarity": "👑 Rare", "image": "assets/stickers/2562.webp"}, {"name": "AdreN (Gold) | Boston 2018", "rarity": "👑 Legendary", "image": "assets/stickers/2563.webp"}, {"name": "Dosia | Boston 2018", "rarity": "💫", "image": "assets/stickers/2564.webp"}, {"name": "Dosia (Foil) | Boston 2018", "rarity": "👑 Rare", "image": "assets/stickers/2565.webp"}, {"name": "Dosia (Gold) | Boston 2018", "rarity": "👑 Legendary", "image": "assets/stickers/2566.webp"}, {"name": "fitch | Boston 2018", "rarity": "💫", "image": "assets/stickers/2567.webp"}, {"name": "fitch (Foil) | Boston 2018", "rarity": "👑 Rare", "image": "assets/stickers/2568.webp"}, {"name": "fitch (Gold) | Boston 2018", "rarity": "👑 Legendary", "image": "assets/stickers/2569.webp"}, {"name": "Hobbit | Boston 2018", "rarity": "💫", "image": "assets/stickers/2570.webp"}, {"name": "Hobbit (Foil) | Boston 2018", "rarity": "👑 Rare", "image": "assets/stickers/2571.webp"}, {"name": "Hobbit (Gold) | Boston 2018", "rarity": "👑 Legendary", "image": "assets/stickers/2572.webp"}, {"name": "mou | Boston 2018", "rarity": "💫", "image": "assets/stickers/2573.webp"}, {"name": "mou (Foil) | Boston 2018", "rarity": "👑 Rare", "image": "assets/stickers/2574.webp"}, {"name": "mou (Gold) | Boston 2018", "rarity": "👑 Legendary", "image": "assets/stickers/2575.webp"}, {"name": "BIT | Boston 2018", "rarity": "💫", "image": "assets/stickers/2576.webp"}, {"name": "BIT (Foil) | Boston 2018", "rarity": "👑 Rare", "image": "assets/stickers/2577.webp"}, {"name": "BIT (Gold) | Boston 2018", "rarity": "👑 Legendary", "image": "assets/stickers/2578.webp"}, {"name": "fnx | Boston 2018", "rarity": "💫", "image": "assets/stickers/2579.webp"}, {"name": "fnx (Foil) | Boston 2018", "rarity": "👑 Rare", "image": "assets/stickers/2580.webp"}, {"name": "fnx (Gold) | Boston 2018", "rarity": "👑 Legendary", "image": "assets/stickers/2581.webp"}, {"name": "HEN1 | Boston 2018", "rarity": "💫", "image": "assets/stickers/2582.webp"}, {"name": "HEN1 (Foil) | Boston 2018", "rarity": "👑 Rare", "image": "assets/stickers/2583.webp"}, {"name": "HEN1 (Gold) | Boston 2018", "rarity": "👑 Legendary", "image": "assets/stickers/2584.webp"}, {"name": "kNgV- | Boston 2018", "rarity": "💫", "image": "assets/stickers/2585.webp"}, {"name": "kNgV- (Foil) | Boston 2018", "rarity": "👑 Rare", "image": "assets/stickers/2586.webp"}, {"name": "kNgV- (Gold) | Boston 2018", "rarity": "👑 Legendary", "image": "assets/stickers/2587.webp"}, {"name": "LUCAS1 | Boston 2018", "rarity": "💫", "image": "assets/stickers/2588.webp"}, {"name": "LUCAS1 (Foil) | Boston 2018", "rarity": "👑 Rare", "image": "assets/stickers/2589.webp"}, {"name": "LUCAS1 (Gold) | Boston 2018", "rarity": "👑 Legendary", "image": "assets/stickers/2590.webp"}, {"name": "device | Boston 2018", "rarity": "💫", "image": "assets/stickers/2591.webp"}, {"name": "device (Foil) | Boston 2018", "rarity": "👑 Rare", "image": "assets/stickers/2592.webp"}, {"name": "device (Gold) | Boston 2018", "rarity": "👑 Legendary", "image": "assets/stickers/2593.webp"}, {"name": "dupreeh | Boston 2018", "rarity": "💫", "image": "assets/stickers/2594.webp"}, {"name": "dupreeh (Foil) | Boston 2018", "rarity": "👑 Rare", "image": "assets/stickers/2595.webp"}, {"name": "dupreeh (Gold) | Boston 2018", "rarity": "👑 Legendary", "image": "assets/stickers/2596.webp"}, {"name": "gla1ve | Boston 2018", "rarity": "💫", "image": "assets/stickers/2597.webp"}, {"name": "gla1ve (Foil) | Boston 2018", "rarity": "👑 Rare", "image": "assets/stickers/2598.webp"}, {"name": "gla1ve (Gold) | Boston 2018", "rarity": "👑 Legendary", "image": "assets/stickers/2599.webp"}, {"name": "Kjaerbye | Boston 2018", "rarity": "💫", "image": "assets/stickers/2600.webp"}, {"name": "Kjaerbye (Foil) | Boston 2018", "rarity": "👑 Rare", "image": "assets/stickers/2601.webp"}, {"name": "Kjaerbye (Gold) | Boston 2018", "rarity": "👑 Legendary", "image": "assets/stickers/2602.webp"}, {"name": "Xyp9x | Boston 2018", "rarity": "💫", "image": "assets/stickers/2603.webp"}, {"name": "Xyp9x (Foil) | Boston 2018", "rarity": "👑 Rare", "image": "assets/stickers/2604.webp"}, {"name": "Xyp9x (Gold) | Boston 2018", "rarity": "👑 Legendary", "image": "assets/stickers/2605.webp"}, {"name": "byali | Boston 2018", "rarity": "💫", "image": "assets/stickers/2606.webp"}, {"name": "byali (Foil) | Boston 2018", "rarity": "👑 Rare", "image": "assets/stickers/2607.webp"}, {"name": "byali (Gold) | Boston 2018", "rarity": "👑 Legendary", "image": "assets/stickers/2608.webp"}, {"name": "NEO | Boston 2018", "rarity": "💫", "image": "assets/stickers/2609.webp"}, {"name": "NEO (Foil) | Boston 2018", "rarity": "👑 Rare", "image": "assets/stickers/2610.webp"}, {"name": "NEO (Gold) | Boston 2018", "rarity": "👑 Legendary", "image": "assets/stickers/2611.webp"}, {"name": "pashaBiceps | Boston 2018", "rarity": "💫", "image": "assets/stickers/2612.webp"}, {"name": "pashaBiceps (Foil) | Boston 2018", "rarity": "👑 Rare", "image": "assets/stickers/2613.webp"}, {"name": "pashaBiceps (Gold) | Boston 2018", "rarity": "👑 Legendary", "image": "assets/stickers/2614.webp"}, {"name": "Snax | Boston 2018", "rarity": "💫", "image": "assets/stickers/2615.webp"}, {"name": "Snax (Foil) | Boston 2018", "rarity": "👑 Rare", "image": "assets/stickers/2616.webp"}, {"name": "Snax (Gold) | Boston 2018", "rarity": "👑 Legendary", "image": "assets/stickers/2617.webp"}, {"name": "TaZ | Boston 2018", "rarity": "💫", "image": "assets/stickers/2618.webp"}, {"name": "TaZ (Foil) | Boston 2018", "rarity": "👑 Rare", "image": "assets/stickers/2619.webp"}, {"name": "TaZ (Gold) | Boston 2018", "rarity": "👑 Legendary", "image": "assets/stickers/2620.webp"}, {"name": "flusha | Boston 2018", "rarity": "💫", "image": "assets/stickers/2621.webp"}, {"name": "flusha (Foil) | Boston 2018", "rarity": "👑 Rare", "image": "assets/stickers/2622.webp"}, {"name": "flusha (Gold) | Boston 2018", "rarity": "👑 Legendary", "image": "assets/stickers/2623.webp"}, {"name": "Golden | Boston 2018", "rarity": "💫", "image": "assets/stickers/2624.webp"}, {"name": "Golden (Foil) | Boston 2018", "rarity": "👑 Rare", "image": "assets/stickers/2625.webp"}, {"name": "Golden (Gold) | Boston 2018", "rarity": "👑 Legendary", "image": "assets/stickers/2626.webp"}, {"name": "JW | Boston 2018", "rarity": "💫", "image": "assets/stickers/2627.webp"}, {"name": "JW (Foil) | Boston 2018", "rarity": "👑 Rare", "image": "assets/stickers/2628.webp"}, {"name": "JW (Gold) | Boston 2018", "rarity": "👑 Legendary", "image": "assets/stickers/2629.webp"}, {"name": "KRIMZ | Boston 2018", "rarity": "💫", "image": "assets/stickers/2630.webp"}, {"name": "KRIMZ (Foil) | Boston 2018", "rarity": "👑 Rare", "image": "assets/stickers/2631.webp"}, {"name": "KRIMZ (Gold) | Boston 2018", "rarity": "👑 Legendary", "image": "assets/stickers/2632.webp"}, {"name": "Lekr0 | Boston 2018", "rarity": "💫", "image": "assets/stickers/2633.webp"}, {"name": "Lekr0 (Foil) | Boston 2018", "rarity": "👑 Rare", "image": "assets/stickers/2634.webp"}, {"name": "Lekr0 (Gold) | Boston 2018", "rarity": "👑 Legendary", "image": "assets/stickers/2635.webp"}, {"name": "coldzera | Boston 2018", "rarity": "💫", "image": "assets/stickers/2636.webp"}, {"name": "coldzera (Foil) | Boston 2018", "rarity": "👑 Rare", "image": "assets/stickers/2637.webp"}, {"name": "coldzera (Gold) | Boston 2018", "rarity": "👑 Legendary", "image": "assets/stickers/2638.webp"}, {"name": "FalleN | Boston 2018", "rarity": "💫", "image": "assets/stickers/2639.webp"}, {"name": "FalleN (Foil) | Boston 2018", "rarity": "👑 Rare", "image": "assets/stickers/2640.webp"}, {"name": "FalleN (Gold) | Boston 2018", "rarity": "👑 Legendary", "image": "assets/stickers/2641.webp"}, {"name": "felps | Boston 2018", "rarity": "💫", "image": "assets/stickers/2642.webp"}, {"name": "felps (Foil) | Boston 2018", "rarity": "👑 Rare", "image": "assets/stickers/2643.webp"}, {"name": "felps (Gold) | Boston 2018", "rarity": "👑 Legendary", "image": "assets/stickers/2644.webp"}, {"name": "fer | Boston 2018", "rarity": "💫", "image": "assets/stickers/2645.webp"}, {"name": "fer (Foil) | Boston 2018", "rarity": "👑 Rare", "image": "assets/stickers/2646.webp"}, {"name": "fer (Gold) | Boston 2018", "rarity": "👑 Legendary", "image": "assets/stickers/2647.webp"}, {"name": "TACO | Boston 2018", "rarity": "💫", "image": "assets/stickers/2648.webp"}, {"name": "TACO (Foil) | Boston 2018", "rarity": "👑 Rare", "image": "assets/stickers/2649.webp"}, {"name": "TACO (Gold) | Boston 2018", "rarity": "👑 Legendary", "image": "assets/stickers/2650.webp"}, {"name": "gob b | Boston 2018", "rarity": "💫", "image": "assets/stickers/2651.webp"}, {"name": "gob b (Foil) | Boston 2018", "rarity": "👑 Rare", "image": "assets/stickers/2652.webp"}, {"name": "gob b (Gold) | Boston 2018", "rarity": "👑 Legendary", "image": "assets/stickers/2653.webp"}, {"name": "keev | Boston 2018", "rarity": "💫", "image": "assets/stickers/2654.webp"}, {"name": "keev (Foil) | Boston 2018", "rarity": "👑 Rare", "image": "assets/stickers/2655.webp"}, {"name": "keev (Gold) | Boston 2018", "rarity": "👑 Legendary", "image": "assets/stickers/2656.webp"}, {"name": "LEGIJA | Boston 2018", "rarity": "💫", "image": "assets/stickers/2657.webp"}, {"name": "LEGIJA (Foil) | Boston 2018", "rarity": "👑 Rare", "image": "assets/stickers/2658.webp"}, {"name": "LEGIJA (Gold) | Boston 2018", "rarity": "👑 Legendary", "image": "assets/stickers/2659.webp"}, {"name": "nex | Boston 2018", "rarity": "💫", "image": "assets/stickers/2660.webp"}, {"name": "nex (Foil) | Boston 2018", "rarity": "👑 Rare", "image": "assets/stickers/2661.webp"}, {"name": "nex (Gold) | Boston 2018", "rarity": "👑 Legendary", "image": "assets/stickers/2662.webp"}, {"name": "tabseN | Boston 2018", "rarity": "💫", "image": "assets/stickers/2663.webp"}, {"name": "tabseN (Foil) | Boston 2018", "rarity": "👑 Rare", "image": "assets/stickers/2664.webp"}, {"name": "tabseN (Gold) | Boston 2018", "rarity": "👑 Legendary", "image": "assets/stickers/2665.webp"}, {"name": "aizy | Boston 2018", "rarity": "💫", "image": "assets/stickers/2666.webp"}, {"name": "aizy (Foil) | Boston 2018", "rarity": "👑 Rare", "image": "assets/stickers/2667.webp"}, {"name": "aizy (Gold) | Boston 2018", "rarity": "👑 Legendary", "image": "assets/stickers/2668.webp"}, {"name": "cajunb | Boston 2018", "rarity": "💫", "image": "assets/stickers/2669.webp"}, {"name": "cajunb (Foil) | Boston 2018", "rarity": "👑 Rare", "image": "assets/stickers/2670.webp"}, {"name": "cajunb (Gold) | Boston 2018", "rarity": "👑 Legendary", "image": "assets/stickers/2671.webp"}, {"name": "k0nfig | Boston 2018", "rarity": "💫", "image": "assets/stickers/2672.webp"}, {"name": "k0nfig (Foil) | Boston 2018", "rarity": "👑 Rare", "image": "assets/stickers/2673.webp"}, {"name": "k0nfig (Gold) | Boston 2018", "rarity": "👑 Legendary", "image": "assets/stickers/2674.webp"}, {"name": "MSL | Boston 2018", "rarity": "💫", "image": "assets/stickers/2675.webp"}, {"name": "MSL (Foil) | Boston 2018", "rarity": "👑 Rare", "image": "assets/stickers/2676.webp"}, {"name": "MSL (Gold) | Boston 2018", "rarity": "👑 Legendary", "image": "assets/stickers/2677.webp"}, {"name": "v4lde | Boston 2018", "rarity": "💫", "image": "assets/stickers/2678.webp"}, {"name": "v4lde (Foil) | Boston 2018", "rarity": "👑 Rare", "image": "assets/stickers/2679.webp"}, {"name": "v4lde (Gold) | Boston 2018", "rarity": "👑 Legendary", "image": "assets/stickers/2680.webp"}],
    },
    "london_2018_legends_autograph": {
        "name": "London 2018 Legends Autograph",
        "emoji": "\ud83d\udd25",
        "price": 1.5,
        "image": "assets/containers/2130.webp",
        "stickers": [{"name": "Golden | London 2018", "rarity": "💫", "image": "assets/stickers/3080.webp"}, {"name": "Golden (Foil) | London 2018", "rarity": "👑 Rare", "image": "assets/stickers/3081.webp"}, {"name": "Golden (Gold) | London 2018", "rarity": "👑 Legendary", "image": "assets/stickers/3082.webp"}, {"name": "autimatic | London 2018", "rarity": "💫", "image": "assets/stickers/3083.webp"}, {"name": "autimatic (Foil) | London 2018", "rarity": "👑 Rare", "image": "assets/stickers/3084.webp"}, {"name": "autimatic (Gold) | London 2018", "rarity": "👑 Legendary", "image": "assets/stickers/3085.webp"}, {"name": "RUSH | London 2018", "rarity": "💫", "image": "assets/stickers/3086.webp"}, {"name": "RUSH (Foil) | London 2018", "rarity": "👑 Rare", "image": "assets/stickers/3087.webp"}, {"name": "RUSH (Gold) | London 2018", "rarity": "👑 Legendary", "image": "assets/stickers/3088.webp"}, {"name": "STYKO | London 2018", "rarity": "💫", "image": "assets/stickers/3089.webp"}, {"name": "STYKO (Foil) | London 2018", "rarity": "👑 Rare", "image": "assets/stickers/3090.webp"}, {"name": "STYKO (Gold) | London 2018", "rarity": "👑 Legendary", "image": "assets/stickers/3091.webp"}, {"name": "Skadoodle | London 2018", "rarity": "💫", "image": "assets/stickers/3092.webp"}, {"name": "Skadoodle (Foil) | London 2018", "rarity": "👑 Rare", "image": "assets/stickers/3093.webp"}, {"name": "Skadoodle (Gold) | London 2018", "rarity": "👑 Legendary", "image": "assets/stickers/3094.webp"}, {"name": "GuardiaN | London 2018", "rarity": "💫", "image": "assets/stickers/3095.webp"}, {"name": "GuardiaN (Foil) | London 2018", "rarity": "👑 Rare", "image": "assets/stickers/3096.webp"}, {"name": "GuardiaN (Gold) | London 2018", "rarity": "👑 Legendary", "image": "assets/stickers/3097.webp"}, {"name": "olofmeister | London 2018", "rarity": "💫", "image": "assets/stickers/3098.webp"}, {"name": "olofmeister (Foil) | London 2018", "rarity": "👑 Rare", "image": "assets/stickers/3099.webp"}, {"name": "olofmeister (Gold) | London 2018", "rarity": "👑 Legendary", "image": "assets/stickers/3100.webp"}, {"name": "karrigan | London 2018", "rarity": "💫", "image": "assets/stickers/3101.webp"}, {"name": "karrigan (Foil) | London 2018", "rarity": "👑 Rare", "image": "assets/stickers/3102.webp"}, {"name": "karrigan (Gold) | London 2018", "rarity": "👑 Legendary", "image": "assets/stickers/3103.webp"}, {"name": "rain | London 2018", "rarity": "💫", "image": "assets/stickers/3104.webp"}, {"name": "rain (Foil) | London 2018", "rarity": "👑 Rare", "image": "assets/stickers/3105.webp"}, {"name": "rain (Gold) | London 2018", "rarity": "👑 Legendary", "image": "assets/stickers/3106.webp"}, {"name": "NiKo | London 2018", "rarity": "💫", "image": "assets/stickers/3107.webp"}, {"name": "NiKo (Foil) | London 2018", "rarity": "👑 Rare", "image": "assets/stickers/3108.webp"}, {"name": "NiKo (Gold) | London 2018", "rarity": "👑 Legendary", "image": "assets/stickers/3109.webp"}, {"name": "electronic | London 2018", "rarity": "💫", "image": "assets/stickers/3110.webp"}, {"name": "electronic (Foil) | London 2018", "rarity": "👑 Rare", "image": "assets/stickers/3111.webp"}, {"name": "electronic (Gold) | London 2018", "rarity": "👑 Legendary", "image": "assets/stickers/3112.webp"}, {"name": "Zeus | London 2018", "rarity": "💫", "image": "assets/stickers/3113.webp"}, {"name": "Zeus (Foil) | London 2018", "rarity": "👑 Rare", "image": "assets/stickers/3114.webp"}, {"name": "Zeus (Gold) | London 2018", "rarity": "👑 Legendary", "image": "assets/stickers/3115.webp"}, {"name": "s1mple | London 2018", "rarity": "💫", "image": "assets/stickers/3116.webp"}, {"name": "s1mple (Foil) | London 2018", "rarity": "👑 Rare", "image": "assets/stickers/3117.webp"}, {"name": "s1mple (Gold) | London 2018", "rarity": "👑 Legendary", "image": "assets/stickers/3118.webp"}, {"name": "Edward | London 2018", "rarity": "💫", "image": "assets/stickers/3119.webp"}, {"name": "Edward (Foil) | London 2018", "rarity": "👑 Rare", "image": "assets/stickers/3120.webp"}, {"name": "Edward (Gold) | London 2018", "rarity": "👑 Legendary", "image": "assets/stickers/3121.webp"}, {"name": "flamie | London 2018", "rarity": "💫", "image": "assets/stickers/3122.webp"}, {"name": "flamie (Foil) | London 2018", "rarity": "👑 Rare", "image": "assets/stickers/3123.webp"}, {"name": "flamie (Gold) | London 2018", "rarity": "👑 Legendary", "image": "assets/stickers/3124.webp"}, {"name": "coldzera | London 2018", "rarity": "💫", "image": "assets/stickers/3125.webp"}, {"name": "coldzera (Foil) | London 2018", "rarity": "👑 Rare", "image": "assets/stickers/3126.webp"}, {"name": "coldzera (Gold) | London 2018", "rarity": "👑 Legendary", "image": "assets/stickers/3127.webp"}, {"name": "FalleN | London 2018", "rarity": "💫", "image": "assets/stickers/3128.webp"}, {"name": "FalleN (Foil) | London 2018", "rarity": "👑 Rare", "image": "assets/stickers/3129.webp"}, {"name": "FalleN (Gold) | London 2018", "rarity": "👑 Legendary", "image": "assets/stickers/3130.webp"}, {"name": "tarik | London 2018", "rarity": "💫", "image": "assets/stickers/3131.webp"}, {"name": "tarik (Foil) | London 2018", "rarity": "👑 Rare", "image": "assets/stickers/3132.webp"}, {"name": "tarik (Gold) | London 2018", "rarity": "👑 Legendary", "image": "assets/stickers/3133.webp"}, {"name": "Stewie2K | London 2018", "rarity": "💫", "image": "assets/stickers/3134.webp"}, {"name": "Stewie2K (Foil) | London 2018", "rarity": "👑 Rare", "image": "assets/stickers/3135.webp"}, {"name": "Stewie2K (Gold) | London 2018", "rarity": "👑 Legendary", "image": "assets/stickers/3136.webp"}, {"name": "fer | London 2018", "rarity": "💫", "image": "assets/stickers/3137.webp"}, {"name": "fer (Foil) | London 2018", "rarity": "👑 Rare", "image": "assets/stickers/3138.webp"}, {"name": "fer (Gold) | London 2018", "rarity": "👑 Legendary", "image": "assets/stickers/3139.webp"}, {"name": "Snax | London 2018", "rarity": "💫", "image": "assets/stickers/3140.webp"}, {"name": "Snax (Foil) | London 2018", "rarity": "👑 Rare", "image": "assets/stickers/3141.webp"}, {"name": "Snax (Gold) | London 2018", "rarity": "👑 Legendary", "image": "assets/stickers/3142.webp"}, {"name": "chrisJ | London 2018", "rarity": "💫", "image": "assets/stickers/3143.webp"}, {"name": "chrisJ (Foil) | London 2018", "rarity": "👑 Rare", "image": "assets/stickers/3144.webp"}, {"name": "chrisJ (Gold) | London 2018", "rarity": "👑 Legendary", "image": "assets/stickers/3145.webp"}, {"name": "ropz | London 2018", "rarity": "💫", "image": "assets/stickers/3146.webp"}, {"name": "ropz (Foil) | London 2018", "rarity": "👑 Rare", "image": "assets/stickers/3147.webp"}, {"name": "ropz (Gold) | London 2018", "rarity": "👑 Legendary", "image": "assets/stickers/3148.webp"}, {"name": "suNny | London 2018", "rarity": "💫", "image": "assets/stickers/3149.webp"}, {"name": "suNny (Foil) | London 2018", "rarity": "👑 Rare", "image": "assets/stickers/3150.webp"}, {"name": "suNny (Gold) | London 2018", "rarity": "👑 Legendary", "image": "assets/stickers/3151.webp"}, {"name": "oskar | London 2018", "rarity": "💫", "image": "assets/stickers/3152.webp"}, {"name": "oskar (Foil) | London 2018", "rarity": "👑 Rare", "image": "assets/stickers/3153.webp"}, {"name": "oskar (Gold) | London 2018", "rarity": "👑 Legendary", "image": "assets/stickers/3154.webp"}, {"name": "jmqa | London 2018", "rarity": "💫", "image": "assets/stickers/3155.webp"}, {"name": "jmqa (Foil) | London 2018", "rarity": "👑 Rare", "image": "assets/stickers/3156.webp"}, {"name": "jmqa (Gold) | London 2018", "rarity": "👑 Legendary", "image": "assets/stickers/3157.webp"}, {"name": "Kvik | London 2018", "rarity": "💫", "image": "assets/stickers/3158.webp"}, {"name": "Kvik (Foil) | London 2018", "rarity": "👑 Rare", "image": "assets/stickers/3159.webp"}, {"name": "Kvik (Gold) | London 2018", "rarity": "👑 Legendary", "image": "assets/stickers/3160.webp"}, {"name": "balblna | London 2018", "rarity": "💫", "image": "assets/stickers/3161.webp"}, {"name": "balblna (Foil) | London 2018", "rarity": "👑 Rare", "image": "assets/stickers/3162.webp"}, {"name": "balblna (Gold) | London 2018", "rarity": "👑 Legendary", "image": "assets/stickers/3163.webp"}, {"name": "waterfaLLZ | London 2018", "rarity": "💫", "image": "assets/stickers/3164.webp"}, {"name": "waterfaLLZ (Foil) | London 2018", "rarity": "👑 Rare", "image": "assets/stickers/3165.webp"}, {"name": "waterfaLLZ (Gold) | London 2018", "rarity": "👑 Legendary", "image": "assets/stickers/3166.webp"}, {"name": "Boombl4 | London 2018", "rarity": "💫", "image": "assets/stickers/3167.webp"}, {"name": "Boombl4 (Foil) | London 2018", "rarity": "👑 Rare", "image": "assets/stickers/3168.webp"}, {"name": "Boombl4 (Gold) | London 2018", "rarity": "👑 Legendary", "image": "assets/stickers/3169.webp"}, {"name": "kennyS | London 2018", "rarity": "💫", "image": "assets/stickers/3170.webp"}, {"name": "kennyS (Foil) | London 2018", "rarity": "👑 Rare", "image": "assets/stickers/3171.webp"}, {"name": "kennyS (Gold) | London 2018", "rarity": "👑 Legendary", "image": "assets/stickers/3172.webp"}, {"name": "bodyy | London 2018", "rarity": "💫", "image": "assets/stickers/3173.webp"}, {"name": "bodyy (Foil) | London 2018", "rarity": "👑 Rare", "image": "assets/stickers/3174.webp"}, {"name": "bodyy (Gold) | London 2018", "rarity": "👑 Legendary", "image": "assets/stickers/3175.webp"}, {"name": "shox | London 2018", "rarity": "💫", "image": "assets/stickers/3176.webp"}, {"name": "shox (Foil) | London 2018", "rarity": "👑 Rare", "image": "assets/stickers/3177.webp"}, {"name": "shox (Gold) | London 2018", "rarity": "👑 Legendary", "image": "assets/stickers/3178.webp"}, {"name": "Ex6TenZ | London 2018", "rarity": "💫", "image": "assets/stickers/3179.webp"}, {"name": "Ex6TenZ (Foil) | London 2018", "rarity": "👑 Rare", "image": "assets/stickers/3180.webp"}, {"name": "Ex6TenZ (Gold) | London 2018", "rarity": "👑 Legendary", "image": "assets/stickers/3181.webp"}, {"name": "SmithZz | London 2018", "rarity": "💫", "image": "assets/stickers/3182.webp"}, {"name": "SmithZz (Foil) | London 2018", "rarity": "👑 Rare", "image": "assets/stickers/3183.webp"}, {"name": "SmithZz (Gold) | London 2018", "rarity": "👑 Legendary", "image": "assets/stickers/3184.webp"}, {"name": "draken | London 2018", "rarity": "💫", "image": "assets/stickers/3185.webp"}, {"name": "draken (Foil) | London 2018", "rarity": "👑 Rare", "image": "assets/stickers/3186.webp"}, {"name": "draken (Gold) | London 2018", "rarity": "👑 Legendary", "image": "assets/stickers/3187.webp"}, {"name": "JW | London 2018", "rarity": "💫", "image": "assets/stickers/3188.webp"}, {"name": "JW (Foil) | London 2018", "rarity": "👑 Rare", "image": "assets/stickers/3189.webp"}, {"name": "JW (Gold) | London 2018", "rarity": "👑 Legendary", "image": "assets/stickers/3190.webp"}, {"name": "KRIMZ | London 2018", "rarity": "💫", "image": "assets/stickers/3191.webp"}, {"name": "KRIMZ (Foil) | London 2018", "rarity": "👑 Rare", "image": "assets/stickers/3192.webp"}, {"name": "KRIMZ (Gold) | London 2018", "rarity": "👑 Legendary", "image": "assets/stickers/3193.webp"}, {"name": "flusha | London 2018", "rarity": "💫", "image": "assets/stickers/3194.webp"}, {"name": "flusha (Foil) | London 2018", "rarity": "👑 Rare", "image": "assets/stickers/3195.webp"}, {"name": "flusha (Gold) | London 2018", "rarity": "👑 Legendary", "image": "assets/stickers/3196.webp"}, {"name": "Xizt | London 2018", "rarity": "💫", "image": "assets/stickers/3197.webp"}, {"name": "Xizt (Foil) | London 2018", "rarity": "👑 Rare", "image": "assets/stickers/3198.webp"}, {"name": "Xizt (Gold) | London 2018", "rarity": "👑 Legendary", "image": "assets/stickers/3199.webp"}],
    },
    "katowice_2019_legends_autograp": {
        "name": "Katowice 2019 Legends Autograph",
        "emoji": "\ud83d\udd25",
        "price": 2.0,
        "image": "assets/containers/2125.webp",
        "stickers": [{"name": "Magisk | Katowice 2019", "rarity": "💫", "image": "assets/stickers/3585.webp"}, {"name": "Magisk (Foil) | Katowice 2019", "rarity": "👑 Rare", "image": "assets/stickers/3586.webp"}, {"name": "Magisk (Gold) | Katowice 2019", "rarity": "👑 Legendary", "image": "assets/stickers/3587.webp"}, {"name": "device | Katowice 2019", "rarity": "💫", "image": "assets/stickers/3588.webp"}, {"name": "device (Foil) | Katowice 2019", "rarity": "👑 Rare", "image": "assets/stickers/3589.webp"}, {"name": "device (Gold) | Katowice 2019", "rarity": "👑 Legendary", "image": "assets/stickers/3590.webp"}, {"name": "Xyp9x | Katowice 2019", "rarity": "💫", "image": "assets/stickers/3591.webp"}, {"name": "Xyp9x (Foil) | Katowice 2019", "rarity": "👑 Rare", "image": "assets/stickers/3592.webp"}, {"name": "Xyp9x (Gold) | Katowice 2019", "rarity": "👑 Legendary", "image": "assets/stickers/3593.webp"}, {"name": "dupreeh | Katowice 2019", "rarity": "💫", "image": "assets/stickers/3594.webp"}, {"name": "dupreeh (Foil) | Katowice 2019", "rarity": "👑 Rare", "image": "assets/stickers/3595.webp"}, {"name": "dupreeh (Gold) | Katowice 2019", "rarity": "👑 Legendary", "image": "assets/stickers/3596.webp"}, {"name": "gla1ve | Katowice 2019", "rarity": "💫", "image": "assets/stickers/3597.webp"}, {"name": "gla1ve (Foil) | Katowice 2019", "rarity": "👑 Rare", "image": "assets/stickers/3598.webp"}, {"name": "gla1ve (Gold) | Katowice 2019", "rarity": "👑 Legendary", "image": "assets/stickers/3599.webp"}, {"name": "gob b | Katowice 2019", "rarity": "💫", "image": "assets/stickers/3615.webp"}, {"name": "gob b (Foil) | Katowice 2019", "rarity": "👑 Rare", "image": "assets/stickers/3616.webp"}, {"name": "gob b (Gold) | Katowice 2019", "rarity": "👑 Legendary", "image": "assets/stickers/3617.webp"}, {"name": "tabseN | Katowice 2019", "rarity": "💫", "image": "assets/stickers/3618.webp"}, {"name": "tabseN (Foil) | Katowice 2019", "rarity": "👑 Rare", "image": "assets/stickers/3619.webp"}, {"name": "tabseN (Gold) | Katowice 2019", "rarity": "👑 Legendary", "image": "assets/stickers/3620.webp"}, {"name": "tiziaN | Katowice 2019", "rarity": "💫", "image": "assets/stickers/3621.webp"}, {"name": "tiziaN (Foil) | Katowice 2019", "rarity": "👑 Rare", "image": "assets/stickers/3622.webp"}, {"name": "tiziaN (Gold) | Katowice 2019", "rarity": "👑 Legendary", "image": "assets/stickers/3623.webp"}, {"name": "XANTARES | Katowice 2019", "rarity": "💫", "image": "assets/stickers/3624.webp"}, {"name": "XANTARES (Foil) | Katowice 2019", "rarity": "👑 Rare", "image": "assets/stickers/3625.webp"}, {"name": "XANTARES (Gold) | Katowice 2019", "rarity": "👑 Legendary", "image": "assets/stickers/3626.webp"}, {"name": "smooya | Katowice 2019", "rarity": "💫", "image": "assets/stickers/3627.webp"}, {"name": "smooya (Foil) | Katowice 2019", "rarity": "👑 Rare", "image": "assets/stickers/3628.webp"}, {"name": "smooya (Gold) | Katowice 2019", "rarity": "👑 Legendary", "image": "assets/stickers/3629.webp"}, {"name": "n0thing | Katowice 2019", "rarity": "💫", "image": "assets/stickers/3645.webp"}, {"name": "n0thing (Foil) | Katowice 2019", "rarity": "👑 Rare", "image": "assets/stickers/3646.webp"}, {"name": "n0thing (Gold) | Katowice 2019", "rarity": "👑 Legendary", "image": "assets/stickers/3647.webp"}, {"name": "Rickeh | Katowice 2019", "rarity": "💫", "image": "assets/stickers/3648.webp"}, {"name": "Rickeh (Foil) | Katowice 2019", "rarity": "👑 Rare", "image": "assets/stickers/3649.webp"}, {"name": "Rickeh (Gold) | Katowice 2019", "rarity": "👑 Legendary", "image": "assets/stickers/3650.webp"}, {"name": "stanislaw | Katowice 2019", "rarity": "💫", "image": "assets/stickers/3651.webp"}, {"name": "stanislaw (Foil) | Katowice 2019", "rarity": "👑 Rare", "image": "assets/stickers/3652.webp"}, {"name": "stanislaw (Gold) | Katowice 2019", "rarity": "👑 Legendary", "image": "assets/stickers/3653.webp"}, {"name": "dephh | Katowice 2019", "rarity": "💫", "image": "assets/stickers/3654.webp"}, {"name": "dephh (Foil) | Katowice 2019", "rarity": "👑 Rare", "image": "assets/stickers/3655.webp"}, {"name": "dephh (Gold) | Katowice 2019", "rarity": "👑 Legendary", "image": "assets/stickers/3656.webp"}, {"name": "ShahZaM | Katowice 2019", "rarity": "💫", "image": "assets/stickers/3657.webp"}, {"name": "ShahZaM (Foil) | Katowice 2019", "rarity": "👑 Rare", "image": "assets/stickers/3658.webp"}, {"name": "ShahZaM (Gold) | Katowice 2019", "rarity": "👑 Legendary", "image": "assets/stickers/3659.webp"}, {"name": "GuardiaN | Katowice 2019", "rarity": "💫", "image": "assets/stickers/3675.webp"}, {"name": "GuardiaN (Foil) | Katowice 2019", "rarity": "👑 Rare", "image": "assets/stickers/3676.webp"}, {"name": "GuardiaN (Gold) | Katowice 2019", "rarity": "👑 Legendary", "image": "assets/stickers/3677.webp"}, {"name": "olofmeister | Katowice 2019", "rarity": "💫", "image": "assets/stickers/3678.webp"}, {"name": "olofmeister (Foil) | Katowice 2019", "rarity": "👑 Rare", "image": "assets/stickers/3679.webp"}, {"name": "olofmeister (Gold) | Katowice 2019", "rarity": "👑 Legendary", "image": "assets/stickers/3680.webp"}, {"name": "rain | Katowice 2019", "rarity": "💫", "image": "assets/stickers/3681.webp"}, {"name": "rain (Foil) | Katowice 2019", "rarity": "👑 Rare", "image": "assets/stickers/3682.webp"}, {"name": "rain (Gold) | Katowice 2019", "rarity": "👑 Legendary", "image": "assets/stickers/3683.webp"}, {"name": "AdreN | Katowice 2019", "rarity": "💫", "image": "assets/stickers/3684.webp"}, {"name": "AdreN (Foil) | Katowice 2019", "rarity": "👑 Rare", "image": "assets/stickers/3685.webp"}, {"name": "AdreN (Gold) | Katowice 2019", "rarity": "👑 Legendary", "image": "assets/stickers/3686.webp"}, {"name": "NiKo | Katowice 2019", "rarity": "💫", "image": "assets/stickers/3687.webp"}, {"name": "NiKo (Foil) | Katowice 2019", "rarity": "👑 Rare", "image": "assets/stickers/3688.webp"}, {"name": "NiKo (Gold) | Katowice 2019", "rarity": "👑 Legendary", "image": "assets/stickers/3689.webp"}, {"name": "DeadFox | Katowice 2019", "rarity": "💫", "image": "assets/stickers/3750.webp"}, {"name": "DeadFox (Foil) | Katowice 2019", "rarity": "👑 Rare", "image": "assets/stickers/3751.webp"}, {"name": "DeadFox (Gold) | Katowice 2019", "rarity": "👑 Legendary", "image": "assets/stickers/3752.webp"}, {"name": "ANGE1 | Katowice 2019", "rarity": "💫", "image": "assets/stickers/3753.webp"}, {"name": "ANGE1 (Foil) | Katowice 2019", "rarity": "👑 Rare", "image": "assets/stickers/3754.webp"}, {"name": "ANGE1 (Gold) | Katowice 2019", "rarity": "👑 Legendary", "image": "assets/stickers/3755.webp"}, {"name": "Hobbit | Katowice 2019", "rarity": "💫", "image": "assets/stickers/3756.webp"}, {"name": "Hobbit (Foil) | Katowice 2019", "rarity": "👑 Rare", "image": "assets/stickers/3757.webp"}, {"name": "Hobbit (Gold) | Katowice 2019", "rarity": "👑 Legendary", "image": "assets/stickers/3758.webp"}, {"name": "ISSAA | Katowice 2019", "rarity": "💫", "image": "assets/stickers/3759.webp"}, {"name": "ISSAA (Foil) | Katowice 2019", "rarity": "👑 Rare", "image": "assets/stickers/3760.webp"}, {"name": "ISSAA (Gold) | Katowice 2019", "rarity": "👑 Legendary", "image": "assets/stickers/3761.webp"}, {"name": "woxic | Katowice 2019", "rarity": "💫", "image": "assets/stickers/3762.webp"}, {"name": "woxic (Foil) | Katowice 2019", "rarity": "👑 Rare", "image": "assets/stickers/3763.webp"}, {"name": "woxic (Gold) | Katowice 2019", "rarity": "👑 Legendary", "image": "assets/stickers/3764.webp"}, {"name": "FalleN | Katowice 2019", "rarity": "💫", "image": "assets/stickers/3765.webp"}, {"name": "FalleN (Foil) | Katowice 2019", "rarity": "👑 Rare", "image": "assets/stickers/3766.webp"}, {"name": "FalleN (Gold) | Katowice 2019", "rarity": "👑 Legendary", "image": "assets/stickers/3767.webp"}, {"name": "felps | Katowice 2019", "rarity": "💫", "image": "assets/stickers/3768.webp"}, {"name": "felps (Foil) | Katowice 2019", "rarity": "👑 Rare", "image": "assets/stickers/3769.webp"}, {"name": "felps (Gold) | Katowice 2019", "rarity": "👑 Legendary", "image": "assets/stickers/3770.webp"}, {"name": "fer | Katowice 2019", "rarity": "💫", "image": "assets/stickers/3771.webp"}, {"name": "fer (Foil) | Katowice 2019", "rarity": "👑 Rare", "image": "assets/stickers/3772.webp"}, {"name": "fer (Gold) | Katowice 2019", "rarity": "👑 Legendary", "image": "assets/stickers/3773.webp"}, {"name": "TACO | Katowice 2019", "rarity": "💫", "image": "assets/stickers/3774.webp"}, {"name": "TACO (Foil) | Katowice 2019", "rarity": "👑 Rare", "image": "assets/stickers/3775.webp"}, {"name": "TACO (Gold) | Katowice 2019", "rarity": "👑 Legendary", "image": "assets/stickers/3776.webp"}, {"name": "coldzera | Katowice 2019", "rarity": "💫", "image": "assets/stickers/3777.webp"}, {"name": "coldzera (Foil) | Katowice 2019", "rarity": "👑 Rare", "image": "assets/stickers/3778.webp"}, {"name": "coldzera (Gold) | Katowice 2019", "rarity": "👑 Legendary", "image": "assets/stickers/3779.webp"}, {"name": "Edward | Katowice 2019", "rarity": "💫", "image": "assets/stickers/3780.webp"}, {"name": "Edward (Foil) | Katowice 2019", "rarity": "👑 Rare", "image": "assets/stickers/3781.webp"}, {"name": "Edward (Gold) | Katowice 2019", "rarity": "👑 Legendary", "image": "assets/stickers/3782.webp"}, {"name": "Zeus | Katowice 2019", "rarity": "💫", "image": "assets/stickers/3783.webp"}, {"name": "Zeus (Foil) | Katowice 2019", "rarity": "👑 Rare", "image": "assets/stickers/3784.webp"}, {"name": "Zeus (Gold) | Katowice 2019", "rarity": "👑 Legendary", "image": "assets/stickers/3785.webp"}, {"name": "s1mple | Katowice 2019", "rarity": "💫", "image": "assets/stickers/3786.webp"}, {"name": "s1mple (Foil) | Katowice 2019", "rarity": "👑 Rare", "image": "assets/stickers/3787.webp"}, {"name": "s1mple (Gold) | Katowice 2019", "rarity": "👑 Legendary", "image": "assets/stickers/3788.webp"}, {"name": "electronic | Katowice 2019", "rarity": "💫", "image": "assets/stickers/3789.webp"}, {"name": "electronic (Foil) | Katowice 2019", "rarity": "👑 Rare", "image": "assets/stickers/3790.webp"}, {"name": "electronic (Gold) | Katowice 2019", "rarity": "👑 Legendary", "image": "assets/stickers/3791.webp"}, {"name": "flamie | Katowice 2019", "rarity": "💫", "image": "assets/stickers/3792.webp"}, {"name": "flamie (Foil) | Katowice 2019", "rarity": "👑 Rare", "image": "assets/stickers/3793.webp"}, {"name": "flamie (Gold) | Katowice 2019", "rarity": "👑 Legendary", "image": "assets/stickers/3794.webp"}, {"name": "nitr0 | Katowice 2019", "rarity": "💫", "image": "assets/stickers/3840.webp"}, {"name": "nitr0 (Foil) | Katowice 2019", "rarity": "👑 Rare", "image": "assets/stickers/3841.webp"}, {"name": "nitr0 (Gold) | Katowice 2019", "rarity": "👑 Legendary", "image": "assets/stickers/3842.webp"}, {"name": "Stewie2K | Katowice 2019", "rarity": "💫", "image": "assets/stickers/3843.webp"}, {"name": "Stewie2K (Foil) | Katowice 2019", "rarity": "👑 Rare", "image": "assets/stickers/3844.webp"}, {"name": "Stewie2K (Gold) | Katowice 2019", "rarity": "👑 Legendary", "image": "assets/stickers/3845.webp"}, {"name": "NAF | Katowice 2019", "rarity": "💫", "image": "assets/stickers/3846.webp"}, {"name": "NAF (Foil) | Katowice 2019", "rarity": "👑 Rare", "image": "assets/stickers/3847.webp"}, {"name": "NAF (Gold) | Katowice 2019", "rarity": "👑 Legendary", "image": "assets/stickers/3848.webp"}, {"name": "Twistzz | Katowice 2019", "rarity": "💫", "image": "assets/stickers/3849.webp"}, {"name": "Twistzz (Foil) | Katowice 2019", "rarity": "👑 Rare", "image": "assets/stickers/3850.webp"}, {"name": "Twistzz (Gold) | Katowice 2019", "rarity": "👑 Legendary", "image": "assets/stickers/3851.webp"}, {"name": "EliGE | Katowice 2019", "rarity": "💫", "image": "assets/stickers/3852.webp"}, {"name": "EliGE (Foil) | Katowice 2019", "rarity": "👑 Rare", "image": "assets/stickers/3853.webp"}, {"name": "EliGE (Gold) | Katowice 2019", "rarity": "👑 Legendary", "image": "assets/stickers/3854.webp"}],
    },
    "berlin_2019_legends_autograph": {
        "name": "Berlin 2019 Legends Autograph",
        "emoji": "\ud83d\udd25",
        "price": 2.0,
        "image": "assets/containers/2087.webp",
        "stickers": [{"name": "Magisk | Berlin 2019", "rarity": "💫", "image": "assets/stickers/4144.webp"}, {"name": "Magisk (Foil) | Berlin 2019", "rarity": "👑 Rare", "image": "assets/stickers/4145.webp"}, {"name": "Magisk (Gold) | Berlin 2019", "rarity": "👑 Legendary", "image": "assets/stickers/4146.webp"}, {"name": "device | Berlin 2019", "rarity": "💫", "image": "assets/stickers/4147.webp"}, {"name": "device (Foil) | Berlin 2019", "rarity": "👑 Rare", "image": "assets/stickers/4148.webp"}, {"name": "device (Gold) | Berlin 2019", "rarity": "👑 Legendary", "image": "assets/stickers/4149.webp"}, {"name": "Xyp9x | Berlin 2019", "rarity": "💫", "image": "assets/stickers/4150.webp"}, {"name": "Xyp9x (Foil) | Berlin 2019", "rarity": "👑 Rare", "image": "assets/stickers/4151.webp"}, {"name": "Xyp9x (Gold) | Berlin 2019", "rarity": "👑 Legendary", "image": "assets/stickers/4152.webp"}, {"name": "dupreeh | Berlin 2019", "rarity": "💫", "image": "assets/stickers/4153.webp"}, {"name": "dupreeh (Foil) | Berlin 2019", "rarity": "👑 Rare", "image": "assets/stickers/4154.webp"}, {"name": "dupreeh (Gold) | Berlin 2019", "rarity": "👑 Legendary", "image": "assets/stickers/4155.webp"}, {"name": "gla1ve | Berlin 2019", "rarity": "💫", "image": "assets/stickers/4156.webp"}, {"name": "gla1ve (Foil) | Berlin 2019", "rarity": "👑 Rare", "image": "assets/stickers/4157.webp"}, {"name": "gla1ve (Gold) | Berlin 2019", "rarity": "👑 Legendary", "image": "assets/stickers/4158.webp"}, {"name": "allu | Berlin 2019", "rarity": "💫", "image": "assets/stickers/4159.webp"}, {"name": "allu (Foil) | Berlin 2019", "rarity": "👑 Rare", "image": "assets/stickers/4160.webp"}, {"name": "allu (Gold) | Berlin 2019", "rarity": "👑 Legendary", "image": "assets/stickers/4161.webp"}, {"name": "Aerial | Berlin 2019", "rarity": "💫", "image": "assets/stickers/4162.webp"}, {"name": "Aerial (Foil) | Berlin 2019", "rarity": "👑 Rare", "image": "assets/stickers/4163.webp"}, {"name": "Aerial (Gold) | Berlin 2019", "rarity": "👑 Legendary", "image": "assets/stickers/4164.webp"}, {"name": "xseveN | Berlin 2019", "rarity": "💫", "image": "assets/stickers/4165.webp"}, {"name": "xseveN (Foil) | Berlin 2019", "rarity": "👑 Rare", "image": "assets/stickers/4166.webp"}, {"name": "xseveN (Gold) | Berlin 2019", "rarity": "👑 Legendary", "image": "assets/stickers/4167.webp"}, {"name": "Aleksib | Berlin 2019", "rarity": "💫", "image": "assets/stickers/4168.webp"}, {"name": "Aleksib (Foil) | Berlin 2019", "rarity": "👑 Rare", "image": "assets/stickers/4169.webp"}, {"name": "Aleksib (Gold) | Berlin 2019", "rarity": "👑 Legendary", "image": "assets/stickers/4170.webp"}, {"name": "sergej | Berlin 2019", "rarity": "💫", "image": "assets/stickers/4171.webp"}, {"name": "sergej (Foil) | Berlin 2019", "rarity": "👑 Rare", "image": "assets/stickers/4172.webp"}, {"name": "sergej (Gold) | Berlin 2019", "rarity": "👑 Legendary", "image": "assets/stickers/4173.webp"}, {"name": "FalleN | Berlin 2019", "rarity": "💫", "image": "assets/stickers/4174.webp"}, {"name": "FalleN (Foil) | Berlin 2019", "rarity": "👑 Rare", "image": "assets/stickers/4175.webp"}, {"name": "FalleN (Gold) | Berlin 2019", "rarity": "👑 Legendary", "image": "assets/stickers/4176.webp"}, {"name": "LUCAS1 | Berlin 2019", "rarity": "💫", "image": "assets/stickers/4177.webp"}, {"name": "LUCAS1 (Foil) | Berlin 2019", "rarity": "👑 Rare", "image": "assets/stickers/4178.webp"}, {"name": "LUCAS1 (Gold) | Berlin 2019", "rarity": "👑 Legendary", "image": "assets/stickers/4179.webp"}, {"name": "fer | Berlin 2019", "rarity": "💫", "image": "assets/stickers/4180.webp"}, {"name": "fer (Foil) | Berlin 2019", "rarity": "👑 Rare", "image": "assets/stickers/4181.webp"}, {"name": "fer (Gold) | Berlin 2019", "rarity": "👑 Legendary", "image": "assets/stickers/4182.webp"}, {"name": "TACO | Berlin 2019", "rarity": "💫", "image": "assets/stickers/4183.webp"}, {"name": "TACO (Foil) | Berlin 2019", "rarity": "👑 Rare", "image": "assets/stickers/4184.webp"}, {"name": "TACO (Gold) | Berlin 2019", "rarity": "👑 Legendary", "image": "assets/stickers/4185.webp"}, {"name": "coldzera | Berlin 2019", "rarity": "💫", "image": "assets/stickers/4186.webp"}, {"name": "coldzera (Foil) | Berlin 2019", "rarity": "👑 Rare", "image": "assets/stickers/4187.webp"}, {"name": "coldzera (Gold) | Berlin 2019", "rarity": "👑 Legendary", "image": "assets/stickers/4188.webp"}, {"name": "Zeus | Berlin 2019", "rarity": "💫", "image": "assets/stickers/4189.webp"}, {"name": "Zeus (Foil) | Berlin 2019", "rarity": "👑 Rare", "image": "assets/stickers/4190.webp"}, {"name": "Zeus (Gold) | Berlin 2019", "rarity": "👑 Legendary", "image": "assets/stickers/4191.webp"}, {"name": "s1mple | Berlin 2019", "rarity": "💫", "image": "assets/stickers/4192.webp"}, {"name": "s1mple (Foil) | Berlin 2019", "rarity": "👑 Rare", "image": "assets/stickers/4193.webp"}, {"name": "s1mple (Gold) | Berlin 2019", "rarity": "👑 Legendary", "image": "assets/stickers/4194.webp"}, {"name": "electronic | Berlin 2019", "rarity": "💫", "image": "assets/stickers/4195.webp"}, {"name": "electronic (Foil) | Berlin 2019", "rarity": "👑 Rare", "image": "assets/stickers/4196.webp"}, {"name": "electronic (Gold) | Berlin 2019", "rarity": "👑 Legendary", "image": "assets/stickers/4197.webp"}, {"name": "flamie | Berlin 2019", "rarity": "💫", "image": "assets/stickers/4198.webp"}, {"name": "flamie (Foil) | Berlin 2019", "rarity": "👑 Rare", "image": "assets/stickers/4199.webp"}, {"name": "flamie (Gold) | Berlin 2019", "rarity": "👑 Legendary", "image": "assets/stickers/4200.webp"}, {"name": "Boombl4 | Berlin 2019", "rarity": "💫", "image": "assets/stickers/4201.webp"}, {"name": "Boombl4 (Foil) | Berlin 2019", "rarity": "👑 Rare", "image": "assets/stickers/4202.webp"}, {"name": "Boombl4 (Gold) | Berlin 2019", "rarity": "👑 Legendary", "image": "assets/stickers/4203.webp"}, {"name": "f0rest | Berlin 2019", "rarity": "💫", "image": "assets/stickers/4204.webp"}, {"name": "f0rest (Foil) | Berlin 2019", "rarity": "👑 Rare", "image": "assets/stickers/4205.webp"}, {"name": "f0rest (Gold) | Berlin 2019", "rarity": "👑 Legendary", "image": "assets/stickers/4206.webp"}, {"name": "Lekr0 | Berlin 2019", "rarity": "💫", "image": "assets/stickers/4207.webp"}, {"name": "Lekr0 (Foil) | Berlin 2019", "rarity": "👑 Rare", "image": "assets/stickers/4208.webp"}, {"name": "Lekr0 (Gold) | Berlin 2019", "rarity": "👑 Legendary", "image": "assets/stickers/4209.webp"}, {"name": "GeT_RiGhT | Berlin 2019", "rarity": "💫", "image": "assets/stickers/4210.webp"}, {"name": "GeT_RiGhT (Foil) | Berlin 2019", "rarity": "👑 Rare", "image": "assets/stickers/4211.webp"}, {"name": "GeT_RiGhT (Gold) | Berlin 2019", "rarity": "👑 Legendary", "image": "assets/stickers/4212.webp"}, {"name": "REZ | Berlin 2019", "rarity": "💫", "image": "assets/stickers/4213.webp"}, {"name": "REZ (Foil) | Berlin 2019", "rarity": "👑 Rare", "image": "assets/stickers/4214.webp"}, {"name": "REZ (Gold) | Berlin 2019", "rarity": "👑 Legendary", "image": "assets/stickers/4215.webp"}, {"name": "Golden | Berlin 2019", "rarity": "💫", "image": "assets/stickers/4216.webp"}, {"name": "Golden (Foil) | Berlin 2019", "rarity": "👑 Rare", "image": "assets/stickers/4217.webp"}, {"name": "Golden (Gold) | Berlin 2019", "rarity": "👑 Legendary", "image": "assets/stickers/4218.webp"}, {"name": "NEO | Berlin 2019", "rarity": "💫", "image": "assets/stickers/4219.webp"}, {"name": "NEO (Foil) | Berlin 2019", "rarity": "👑 Rare", "image": "assets/stickers/4220.webp"}, {"name": "NEO (Gold) | Berlin 2019", "rarity": "👑 Legendary", "image": "assets/stickers/4221.webp"}, {"name": "GuardiaN | Berlin 2019", "rarity": "💫", "image": "assets/stickers/4222.webp"}, {"name": "GuardiaN (Foil) | Berlin 2019", "rarity": "👑 Rare", "image": "assets/stickers/4223.webp"}, {"name": "GuardiaN (Gold) | Berlin 2019", "rarity": "👑 Legendary", "image": "assets/stickers/4224.webp"}, {"name": "olofmeister | Berlin 2019", "rarity": "💫", "image": "assets/stickers/4225.webp"}, {"name": "olofmeister (Foil) | Berlin 2019", "rarity": "👑 Rare", "image": "assets/stickers/4226.webp"}, {"name": "olofmeister (Gold) | Berlin 2019", "rarity": "👑 Legendary", "image": "assets/stickers/4227.webp"}, {"name": "rain | Berlin 2019", "rarity": "💫", "image": "assets/stickers/4228.webp"}, {"name": "rain (Foil) | Berlin 2019", "rarity": "👑 Rare", "image": "assets/stickers/4229.webp"}, {"name": "rain (Gold) | Berlin 2019", "rarity": "👑 Legendary", "image": "assets/stickers/4230.webp"}, {"name": "NiKo | Berlin 2019", "rarity": "💫", "image": "assets/stickers/4231.webp"}, {"name": "NiKo (Foil) | Berlin 2019", "rarity": "👑 Rare", "image": "assets/stickers/4232.webp"}, {"name": "NiKo (Gold) | Berlin 2019", "rarity": "👑 Legendary", "image": "assets/stickers/4233.webp"}, {"name": "nitr0 | Berlin 2019", "rarity": "💫", "image": "assets/stickers/4234.webp"}, {"name": "nitr0 (Foil) | Berlin 2019", "rarity": "👑 Rare", "image": "assets/stickers/4235.webp"}, {"name": "nitr0 (Gold) | Berlin 2019", "rarity": "👑 Legendary", "image": "assets/stickers/4236.webp"}, {"name": "Stewie2K | Berlin 2019", "rarity": "💫", "image": "assets/stickers/4237.webp"}, {"name": "Stewie2K (Foil) | Berlin 2019", "rarity": "👑 Rare", "image": "assets/stickers/4238.webp"}, {"name": "Stewie2K (Gold) | Berlin 2019", "rarity": "👑 Legendary", "image": "assets/stickers/4239.webp"}, {"name": "NAF | Berlin 2019", "rarity": "💫", "image": "assets/stickers/4240.webp"}, {"name": "NAF (Foil) | Berlin 2019", "rarity": "👑 Rare", "image": "assets/stickers/4241.webp"}, {"name": "NAF (Gold) | Berlin 2019", "rarity": "👑 Legendary", "image": "assets/stickers/4242.webp"}, {"name": "Twistzz | Berlin 2019", "rarity": "💫", "image": "assets/stickers/4243.webp"}, {"name": "Twistzz (Foil) | Berlin 2019", "rarity": "👑 Rare", "image": "assets/stickers/4244.webp"}, {"name": "Twistzz (Gold) | Berlin 2019", "rarity": "👑 Legendary", "image": "assets/stickers/4245.webp"}, {"name": "EliGE | Berlin 2019", "rarity": "💫", "image": "assets/stickers/4246.webp"}, {"name": "EliGE (Foil) | Berlin 2019", "rarity": "👑 Rare", "image": "assets/stickers/4247.webp"}, {"name": "EliGE (Gold) | Berlin 2019", "rarity": "👑 Legendary", "image": "assets/stickers/4248.webp"}, {"name": "Gratisfaction | Berlin 2019", "rarity": "💫", "image": "assets/stickers/4249.webp"}, {"name": "Gratisfaction (Foil) | Berlin 2019", "rarity": "👑 Rare", "image": "assets/stickers/4250.webp"}, {"name": "Gratisfaction (Gold) | Berlin 2019", "rarity": "👑 Legendary", "image": "assets/stickers/4251.webp"}, {"name": "jks | Berlin 2019", "rarity": "💫", "image": "assets/stickers/4252.webp"}, {"name": "jks (Foil) | Berlin 2019", "rarity": "👑 Rare", "image": "assets/stickers/4253.webp"}, {"name": "jks (Gold) | Berlin 2019", "rarity": "👑 Legendary", "image": "assets/stickers/4254.webp"}, {"name": "AZR | Berlin 2019", "rarity": "💫", "image": "assets/stickers/4255.webp"}, {"name": "AZR (Foil) | Berlin 2019", "rarity": "👑 Rare", "image": "assets/stickers/4256.webp"}, {"name": "AZR (Gold) | Berlin 2019", "rarity": "👑 Legendary", "image": "assets/stickers/4257.webp"}, {"name": "jkaem | Berlin 2019", "rarity": "💫", "image": "assets/stickers/4258.webp"}, {"name": "jkaem (Foil) | Berlin 2019", "rarity": "👑 Rare", "image": "assets/stickers/4259.webp"}, {"name": "jkaem (Gold) | Berlin 2019", "rarity": "👑 Legendary", "image": "assets/stickers/4260.webp"}, {"name": "Liazz | Berlin 2019", "rarity": "💫", "image": "assets/stickers/4261.webp"}, {"name": "Liazz (Foil) | Berlin 2019", "rarity": "👑 Rare", "image": "assets/stickers/4262.webp"}, {"name": "Liazz (Gold) | Berlin 2019", "rarity": "👑 Legendary", "image": "assets/stickers/4263.webp"}],
    },
    "krakow_2017_legends_autograph": {
        "name": "Krakow 2017 Legends Autograph",
        "emoji": "\ud83d\udcab",
        "price": 1.5,
        "image": "assets/containers/2129.webp",
        "stickers": [{"name": "device | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2148.webp"}, {"name": "device (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2149.webp"}, {"name": "device (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2150.webp"}, {"name": "dupreeh | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2151.webp"}, {"name": "dupreeh (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2152.webp"}, {"name": "dupreeh (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2153.webp"}, {"name": "gla1ve | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2154.webp"}, {"name": "gla1ve (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2155.webp"}, {"name": "gla1ve (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2156.webp"}, {"name": "Kjaerbye | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2157.webp"}, {"name": "Kjaerbye (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2158.webp"}, {"name": "Kjaerbye (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2159.webp"}, {"name": "Xyp9x | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2160.webp"}, {"name": "Xyp9x (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2161.webp"}, {"name": "Xyp9x (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2162.webp"}, {"name": "byali | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2163.webp"}, {"name": "byali (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2164.webp"}, {"name": "byali (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2165.webp"}, {"name": "NEO | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2166.webp"}, {"name": "NEO (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2167.webp"}, {"name": "NEO (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2168.webp"}, {"name": "pashaBiceps | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2169.webp"}, {"name": "pashaBiceps (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2170.webp"}, {"name": "pashaBiceps (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2171.webp"}, {"name": "Snax | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2172.webp"}, {"name": "Snax (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2173.webp"}, {"name": "Snax (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2174.webp"}, {"name": "TaZ | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2175.webp"}, {"name": "TaZ (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2176.webp"}, {"name": "TaZ (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2177.webp"}, {"name": "dennis | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2178.webp"}, {"name": "dennis (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2179.webp"}, {"name": "dennis (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2180.webp"}, {"name": "flusha | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2181.webp"}, {"name": "flusha (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2182.webp"}, {"name": "flusha (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2183.webp"}, {"name": "JW | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2184.webp"}, {"name": "JW (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2185.webp"}, {"name": "JW (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2186.webp"}, {"name": "KRIMZ | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2187.webp"}, {"name": "KRIMZ (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2188.webp"}, {"name": "KRIMZ (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2189.webp"}, {"name": "olofmeister | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2190.webp"}, {"name": "olofmeister (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2191.webp"}, {"name": "olofmeister (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2192.webp"}, {"name": "coldzera | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2193.webp"}, {"name": "coldzera (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2194.webp"}, {"name": "coldzera (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2195.webp"}, {"name": "FalleN | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2196.webp"}, {"name": "FalleN (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2197.webp"}, {"name": "FalleN (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2198.webp"}, {"name": "felps | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2199.webp"}, {"name": "felps (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2200.webp"}, {"name": "felps (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2201.webp"}, {"name": "fer | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2202.webp"}, {"name": "fer (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2203.webp"}, {"name": "fer (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2204.webp"}, {"name": "TACO | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2205.webp"}, {"name": "TACO (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2206.webp"}, {"name": "TACO (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2207.webp"}, {"name": "Edward | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2208.webp"}, {"name": "Edward (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2209.webp"}, {"name": "Edward (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2210.webp"}, {"name": "flamie | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2211.webp"}, {"name": "flamie (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2212.webp"}, {"name": "flamie (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2213.webp"}, {"name": "GuardiaN | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2214.webp"}, {"name": "GuardiaN (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2215.webp"}, {"name": "GuardiaN (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2216.webp"}, {"name": "s1mple | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2217.webp"}, {"name": "s1mple (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2218.webp"}, {"name": "s1mple (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2219.webp"}, {"name": "seized | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2220.webp"}, {"name": "seized (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2221.webp"}, {"name": "seized (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2222.webp"}, {"name": "AdreN | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2223.webp"}, {"name": "AdreN (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2224.webp"}, {"name": "AdreN (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2225.webp"}, {"name": "Dosia | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2226.webp"}, {"name": "Dosia (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2227.webp"}, {"name": "Dosia (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2228.webp"}, {"name": "Hobbit | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2229.webp"}, {"name": "Hobbit (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2230.webp"}, {"name": "Hobbit (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2231.webp"}, {"name": "mou | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2232.webp"}, {"name": "mou (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2233.webp"}, {"name": "mou (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2234.webp"}, {"name": "Zeus | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2235.webp"}, {"name": "Zeus (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2236.webp"}, {"name": "Zeus (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2237.webp"}, {"name": "aizy | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2238.webp"}, {"name": "aizy (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2239.webp"}, {"name": "aizy (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2240.webp"}, {"name": "cajunb | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2241.webp"}, {"name": "cajunb (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2242.webp"}, {"name": "cajunb (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2243.webp"}, {"name": "k0nfig | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2244.webp"}, {"name": "k0nfig (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2245.webp"}, {"name": "k0nfig (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2246.webp"}, {"name": "Magisk | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2247.webp"}, {"name": "Magisk (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2248.webp"}, {"name": "Magisk (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2249.webp"}, {"name": "MSL | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2250.webp"}, {"name": "MSL (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2251.webp"}, {"name": "MSL (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2252.webp"}, {"name": "allu | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2253.webp"}, {"name": "allu (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2254.webp"}, {"name": "allu (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2255.webp"}, {"name": "karrigan | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2256.webp"}, {"name": "karrigan (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2257.webp"}, {"name": "karrigan (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2258.webp"}, {"name": "kioShiMa | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2259.webp"}, {"name": "kioShiMa (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2260.webp"}, {"name": "kioShiMa (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2261.webp"}, {"name": "NiKo | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2262.webp"}, {"name": "NiKo (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2263.webp"}, {"name": "NiKo (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2264.webp"}, {"name": "rain | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2265.webp"}, {"name": "rain (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2266.webp"}, {"name": "rain (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2267.webp"}],
    },
    "krakow_2017_challengers_autogr": {
        "name": "Krakow 2017 Challengers Autograph",
        "emoji": "\ud83d\udcab",
        "price": 1.0,
        "image": "assets/containers/2128.webp",
        "stickers": [{"name": "chrisJ | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2268.webp"}, {"name": "chrisJ (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2269.webp"}, {"name": "chrisJ (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2270.webp"}, {"name": "denis | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2271.webp"}, {"name": "denis (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2272.webp"}, {"name": "denis (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2273.webp"}, {"name": "loWel | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2274.webp"}, {"name": "loWel (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2275.webp"}, {"name": "loWel (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2276.webp"}, {"name": "oskar | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2277.webp"}, {"name": "oskar (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2278.webp"}, {"name": "oskar (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2279.webp"}, {"name": "ropz | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2280.webp"}, {"name": "ropz (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2281.webp"}, {"name": "ropz (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2282.webp"}, {"name": "apEX | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2283.webp"}, {"name": "apEX (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2284.webp"}, {"name": "apEX (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2285.webp"}, {"name": "bodyy | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2286.webp"}, {"name": "bodyy (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2287.webp"}, {"name": "bodyy (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2288.webp"}, {"name": "kennyS | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2289.webp"}, {"name": "kennyS (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2290.webp"}, {"name": "kennyS (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2291.webp"}, {"name": "NBK- | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2292.webp"}, {"name": "NBK- (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2293.webp"}, {"name": "NBK- (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2294.webp"}, {"name": "shox | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2295.webp"}, {"name": "shox (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2296.webp"}, {"name": "shox (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2297.webp"}, {"name": "gob b | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2298.webp"}, {"name": "gob b (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2299.webp"}, {"name": "gob b (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2300.webp"}, {"name": "keev | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2301.webp"}, {"name": "keev (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2302.webp"}, {"name": "keev (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2303.webp"}, {"name": "LEGIJA | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2304.webp"}, {"name": "LEGIJA (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2305.webp"}, {"name": "LEGIJA (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2306.webp"}, {"name": "nex | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2307.webp"}, {"name": "nex (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2308.webp"}, {"name": "nex (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2309.webp"}, {"name": "tabseN | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2310.webp"}, {"name": "tabseN (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2311.webp"}, {"name": "tabseN (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2312.webp"}, {"name": "autimatic | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2313.webp"}, {"name": "autimatic (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2314.webp"}, {"name": "autimatic (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2315.webp"}, {"name": "n0thing | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2316.webp"}, {"name": "n0thing (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2317.webp"}, {"name": "n0thing (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2318.webp"}, {"name": "shroud | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2319.webp"}, {"name": "shroud (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2320.webp"}, {"name": "shroud (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2321.webp"}, {"name": "Skadoodle | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2322.webp"}, {"name": "Skadoodle (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2323.webp"}, {"name": "Skadoodle (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2324.webp"}, {"name": "Stewie2K | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2325.webp"}, {"name": "Stewie2K (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2326.webp"}, {"name": "Stewie2K (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2327.webp"}, {"name": "HS | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2328.webp"}, {"name": "HS (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2329.webp"}, {"name": "HS (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2330.webp"}, {"name": "innocent | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2331.webp"}, {"name": "innocent (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2332.webp"}, {"name": "innocent (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2333.webp"}, {"name": "kRYSTAL | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2334.webp"}, {"name": "kRYSTAL (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2335.webp"}, {"name": "kRYSTAL (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2336.webp"}, {"name": "suNny | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2337.webp"}, {"name": "suNny (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2338.webp"}, {"name": "suNny (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2339.webp"}, {"name": "zehN | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2340.webp"}, {"name": "zehN (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2341.webp"}, {"name": "zehN (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2342.webp"}, {"name": "B1ad3 | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2343.webp"}, {"name": "B1ad3 (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2344.webp"}, {"name": "B1ad3 (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2345.webp"}, {"name": "electronic | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2346.webp"}, {"name": "electronic (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2347.webp"}, {"name": "electronic (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2348.webp"}, {"name": "markeloff | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2349.webp"}, {"name": "markeloff (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2350.webp"}, {"name": "markeloff (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2351.webp"}, {"name": "wayLander | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2352.webp"}, {"name": "wayLander (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2353.webp"}, {"name": "wayLander (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2354.webp"}, {"name": "WorldEdit | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2355.webp"}, {"name": "WorldEdit (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2356.webp"}, {"name": "WorldEdit (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2357.webp"}, {"name": "boltz | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2358.webp"}, {"name": "boltz (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2359.webp"}, {"name": "boltz (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2360.webp"}, {"name": "HEN1 | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2361.webp"}, {"name": "HEN1 (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2362.webp"}, {"name": "HEN1 (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2363.webp"}, {"name": "kNgV- | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2364.webp"}, {"name": "kNgV- (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2365.webp"}, {"name": "kNgV- (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2366.webp"}, {"name": "LUCAS1 | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2367.webp"}, {"name": "LUCAS1 (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2368.webp"}, {"name": "LUCAS1 (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2369.webp"}, {"name": "steel | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2370.webp"}, {"name": "steel (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2371.webp"}, {"name": "steel (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2372.webp"}, {"name": "chopper | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2373.webp"}, {"name": "chopper (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2374.webp"}, {"name": "chopper (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2375.webp"}, {"name": "hutji | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2376.webp"}, {"name": "hutji (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2377.webp"}, {"name": "hutji (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2378.webp"}, {"name": "jR | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2379.webp"}, {"name": "jR (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2380.webp"}, {"name": "jR (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2381.webp"}, {"name": "keshandr | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2382.webp"}, {"name": "keshandr (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2383.webp"}, {"name": "keshandr (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2384.webp"}, {"name": "mir | Krakow 2017", "rarity": "💫", "image": "assets/stickers/2385.webp"}, {"name": "mir (Foil) | Krakow 2017", "rarity": "👑 Rare", "image": "assets/stickers/2386.webp"}, {"name": "mir (Gold) | Krakow 2017", "rarity": "👑 Legendary", "image": "assets/stickers/2387.webp"}],
    },
    "cologne_2016_legends_holo_foil": {
        "name": "Cologne 2016 Legends (Holo/Foil)",
        "emoji": "\u2728",
        "price": 2.0,
        "image": "assets/containers/2199.webp",
        "stickers": [{"name": "Ninjas in Pyjamas (Holo) | Cologne 2016", "rarity": "👑 Rare", "image": "assets/stickers/1318.webp"}, {"name": "Ninjas in Pyjamas (Foil) | Cologne 2016", "rarity": "🔥", "image": "assets/stickers/1319.webp"}, {"name": "Counter Logic Gaming (Holo) | Cologne 2016", "rarity": "👑 Rare", "image": "assets/stickers/1326.webp"}, {"name": "Counter Logic Gaming (Foil) | Cologne 2016", "rarity": "🔥", "image": "assets/stickers/1327.webp"}, {"name": "Team Liquid (Holo) | Cologne 2016", "rarity": "👑 Rare", "image": "assets/stickers/1338.webp"}, {"name": "Team Liquid (Foil) | Cologne 2016", "rarity": "🔥", "image": "assets/stickers/1339.webp"}, {"name": "Natus Vincere (Holo) | Cologne 2016", "rarity": "👑 Rare", "image": "assets/stickers/1346.webp"}, {"name": "Natus Vincere (Foil) | Cologne 2016", "rarity": "🔥", "image": "assets/stickers/1347.webp"}, {"name": "Virtus.Pro (Holo) | Cologne 2016", "rarity": "👑 Rare", "image": "assets/stickers/1350.webp"}, {"name": "Virtus.Pro (Foil) | Cologne 2016", "rarity": "🔥", "image": "assets/stickers/1351.webp"}, {"name": "SK Gaming (Holo) | Cologne 2016", "rarity": "👑 Rare", "image": "assets/stickers/1354.webp"}, {"name": "SK Gaming (Foil) | Cologne 2016", "rarity": "🔥", "image": "assets/stickers/1355.webp"}, {"name": "Astralis (Holo) | Cologne 2016", "rarity": "👑 Rare", "image": "assets/stickers/1366.webp"}, {"name": "Astralis (Foil) | Cologne 2016", "rarity": "🔥", "image": "assets/stickers/1367.webp"}, {"name": "Fnatic (Holo) | Cologne 2016", "rarity": "👑 Rare", "image": "assets/stickers/1374.webp"}, {"name": "Fnatic (Foil) | Cologne 2016", "rarity": "🔥", "image": "assets/stickers/1375.webp"}, {"name": "ESL (Holo) | Cologne 2016", "rarity": "👑 Rare", "image": "assets/stickers/1382.webp"}, {"name": "ESL (Foil) | Cologne 2016", "rarity": "🔥", "image": "assets/stickers/1383.webp"}],
    },
    "mlg_columbus_2016_legends_holo": {
        "name": "MLG Columbus 2016 Legends (Holo/Foil)",
        "emoji": "\u2728",
        "price": 2.0,
        "image": "assets/containers/2197.webp",
        "stickers": [{"name": "Ninjas in Pyjamas (Holo) | MLG Columbus 2016", "rarity": "👑 Rare", "image": "assets/stickers/1008.webp"}, {"name": "Ninjas in Pyjamas (Foil) | MLG Columbus 2016", "rarity": "🔥", "image": "assets/stickers/1009.webp"}, {"name": "Natus Vincere (Holo) | MLG Columbus 2016", "rarity": "👑 Rare", "image": "assets/stickers/1036.webp"}, {"name": "Natus Vincere (Foil) | MLG Columbus 2016", "rarity": "🔥", "image": "assets/stickers/1037.webp"}, {"name": "Virtus.Pro (Holo) | MLG Columbus 2016", "rarity": "👑 Rare", "image": "assets/stickers/1040.webp"}, {"name": "Virtus.Pro (Foil) | MLG Columbus 2016", "rarity": "🔥", "image": "assets/stickers/1041.webp"}, {"name": "FaZe Clan (Holo) | MLG Columbus 2016", "rarity": "👑 Rare", "image": "assets/stickers/1052.webp"}, {"name": "FaZe Clan (Foil) | MLG Columbus 2016", "rarity": "🔥", "image": "assets/stickers/1053.webp"}, {"name": "Astralis (Holo) | MLG Columbus 2016", "rarity": "👑 Rare", "image": "assets/stickers/1056.webp"}, {"name": "Astralis (Foil) | MLG Columbus 2016", "rarity": "🔥", "image": "assets/stickers/1057.webp"}, {"name": "Team EnVyUs (Holo) | MLG Columbus 2016", "rarity": "👑 Rare", "image": "assets/stickers/1060.webp"}, {"name": "Team EnVyUs (Foil) | MLG Columbus 2016", "rarity": "🔥", "image": "assets/stickers/1061.webp"}, {"name": "Fnatic (Holo) | MLG Columbus 2016", "rarity": "👑 Rare", "image": "assets/stickers/1064.webp"}, {"name": "Fnatic (Foil) | MLG Columbus 2016", "rarity": "🔥", "image": "assets/stickers/1065.webp"}, {"name": "Luminosity Gaming (Holo) | MLG Columbus 2016", "rarity": "👑 Rare", "image": "assets/stickers/1068.webp"}, {"name": "Luminosity Gaming (Foil) | MLG Columbus 2016", "rarity": "🔥", "image": "assets/stickers/1069.webp"}, {"name": "MLG (Holo) | MLG Columbus 2016", "rarity": "👑 Rare", "image": "assets/stickers/1072.webp"}, {"name": "MLG (Foil) | MLG Columbus 2016", "rarity": "🔥", "image": "assets/stickers/1073.webp"}],
    },
    "budapest_2025_challengers_stic": {
        "name": "Budapest 2025 Challengers Sticker",
        "emoji": "\ud83c\udf1f",
        "price": 1.5,
        "image": "assets/containers/2097.webp",
        "stickers": [{"name": "Aurora | Budapest 2025", "rarity": "💫", "image": "assets/stickers/9521.webp"}, {"name": "Aurora (Embroidered) | Budapest 2025", "rarity": "👑 Rare", "image": "assets/stickers/9522.webp"}, {"name": "Aurora (Holo) | Budapest 2025", "rarity": "🔥", "image": "assets/stickers/9523.webp"}, {"name": "Aurora (Gold) | Budapest 2025", "rarity": "👑 Legendary", "image": "assets/stickers/9524.webp"}, {"name": "Natus Vincere | Budapest 2025", "rarity": "💫", "image": "assets/stickers/9525.webp"}, {"name": "Natus Vincere (Embroidered) | Budapest 2025", "rarity": "👑 Rare", "image": "assets/stickers/9526.webp"}, {"name": "Natus Vincere (Holo) | Budapest 2025", "rarity": "🔥", "image": "assets/stickers/9527.webp"}, {"name": "Natus Vincere (Gold) | Budapest 2025", "rarity": "👑 Legendary", "image": "assets/stickers/9528.webp"}, {"name": "Team Liquid | Budapest 2025", "rarity": "💫", "image": "assets/stickers/9529.webp"}, {"name": "Team Liquid (Embroidered) | Budapest 2025", "rarity": "👑 Rare", "image": "assets/stickers/9530.webp"}, {"name": "Team Liquid (Holo) | Budapest 2025", "rarity": "🔥", "image": "assets/stickers/9531.webp"}, {"name": "Team Liquid (Gold) | Budapest 2025", "rarity": "👑 Legendary", "image": "assets/stickers/9532.webp"}, {"name": "3DMAX | Budapest 2025", "rarity": "💫", "image": "assets/stickers/9533.webp"}, {"name": "3DMAX (Embroidered) | Budapest 2025", "rarity": "👑 Rare", "image": "assets/stickers/9534.webp"}, {"name": "3DMAX (Holo) | Budapest 2025", "rarity": "🔥", "image": "assets/stickers/9535.webp"}, {"name": "3DMAX (Gold) | Budapest 2025", "rarity": "👑 Legendary", "image": "assets/stickers/9536.webp"}, {"name": "Astralis | Budapest 2025", "rarity": "💫", "image": "assets/stickers/9537.webp"}, {"name": "Astralis (Embroidered) | Budapest 2025", "rarity": "👑 Rare", "image": "assets/stickers/9538.webp"}, {"name": "Astralis (Holo) | Budapest 2025", "rarity": "🔥", "image": "assets/stickers/9539.webp"}, {"name": "Astralis (Gold) | Budapest 2025", "rarity": "👑 Legendary", "image": "assets/stickers/9540.webp"}, {"name": "TYLOO | Budapest 2025", "rarity": "💫", "image": "assets/stickers/9541.webp"}, {"name": "TYLOO (Embroidered) | Budapest 2025", "rarity": "👑 Rare", "image": "assets/stickers/9542.webp"}, {"name": "TYLOO (Holo) | Budapest 2025", "rarity": "🔥", "image": "assets/stickers/9543.webp"}, {"name": "TYLOO (Gold) | Budapest 2025", "rarity": "👑 Legendary", "image": "assets/stickers/9544.webp"}, {"name": "MIBR | Budapest 2025", "rarity": "💫", "image": "assets/stickers/9545.webp"}, {"name": "MIBR (Embroidered) | Budapest 2025", "rarity": "👑 Rare", "image": "assets/stickers/9546.webp"}, {"name": "MIBR (Holo) | Budapest 2025", "rarity": "🔥", "image": "assets/stickers/9547.webp"}, {"name": "MIBR (Gold) | Budapest 2025", "rarity": "👑 Legendary", "image": "assets/stickers/9548.webp"}, {"name": "Passion UA | Budapest 2025", "rarity": "💫", "image": "assets/stickers/9549.webp"}, {"name": "Passion UA (Embroidered) | Budapest 2025", "rarity": "👑 Rare", "image": "assets/stickers/9550.webp"}, {"name": "Passion UA (Holo) | Budapest 2025", "rarity": "🔥", "image": "assets/stickers/9551.webp"}, {"name": "Passion UA (Gold) | Budapest 2025", "rarity": "👑 Legendary", "image": "assets/stickers/9552.webp"}, {"name": "StarLadder | Budapest 2025", "rarity": "💫", "image": "assets/stickers/9617.webp"}, {"name": "StarLadder (Embroidered) | Budapest 2025", "rarity": "👑 Rare", "image": "assets/stickers/9618.webp"}, {"name": "StarLadder (Holo) | Budapest 2025", "rarity": "🔥", "image": "assets/stickers/9619.webp"}, {"name": "StarLadder (Gold) | Budapest 2025", "rarity": "👑 Legendary", "image": "assets/stickers/9620.webp"}],
    },
    "copenhagen_2024_challengers_st": {
        "name": "Copenhagen 2024 Challengers Sticker",
        "emoji": "\ud83c\udf1f",
        "price": 1.5,
        "image": "assets/containers/2111.webp",
        "stickers": [{"name": "Cloud9 | Copenhagen 2024", "rarity": "💫", "image": "assets/stickers/7286.webp"}, {"name": "Cloud9 (Glitter) | Copenhagen 2024", "rarity": "👑 Rare", "image": "assets/stickers/7287.webp"}, {"name": "Cloud9 (Holo) | Copenhagen 2024", "rarity": "🔥", "image": "assets/stickers/7288.webp"}, {"name": "Cloud9 (Gold) | Copenhagen 2024", "rarity": "👑 Legendary", "image": "assets/stickers/7289.webp"}, {"name": "ENCE | Copenhagen 2024", "rarity": "💫", "image": "assets/stickers/7290.webp"}, {"name": "ENCE (Glitter) | Copenhagen 2024", "rarity": "👑 Rare", "image": "assets/stickers/7291.webp"}, {"name": "ENCE (Holo) | Copenhagen 2024", "rarity": "🔥", "image": "assets/stickers/7292.webp"}, {"name": "ENCE (Gold) | Copenhagen 2024", "rarity": "👑 Legendary", "image": "assets/stickers/7293.webp"}, {"name": "FURIA | Copenhagen 2024", "rarity": "💫", "image": "assets/stickers/7294.webp"}, {"name": "FURIA (Glitter) | Copenhagen 2024", "rarity": "👑 Rare", "image": "assets/stickers/7295.webp"}, {"name": "FURIA (Holo) | Copenhagen 2024", "rarity": "🔥", "image": "assets/stickers/7296.webp"}, {"name": "FURIA (Gold) | Copenhagen 2024", "rarity": "👑 Legendary", "image": "assets/stickers/7297.webp"}, {"name": "Heroic | Copenhagen 2024", "rarity": "💫", "image": "assets/stickers/7298.webp"}, {"name": "Heroic (Glitter) | Copenhagen 2024", "rarity": "👑 Rare", "image": "assets/stickers/7299.webp"}, {"name": "Heroic (Holo) | Copenhagen 2024", "rarity": "🔥", "image": "assets/stickers/7300.webp"}, {"name": "Heroic (Gold) | Copenhagen 2024", "rarity": "👑 Legendary", "image": "assets/stickers/7301.webp"}, {"name": "Eternal Fire | Copenhagen 2024", "rarity": "💫", "image": "assets/stickers/7302.webp"}, {"name": "Eternal Fire (Glitter) | Copenhagen 2024", "rarity": "👑 Rare", "image": "assets/stickers/7303.webp"}, {"name": "Eternal Fire (Holo) | Copenhagen 2024", "rarity": "🔥", "image": "assets/stickers/7304.webp"}, {"name": "Eternal Fire (Gold) | Copenhagen 2024", "rarity": "👑 Legendary", "image": "assets/stickers/7305.webp"}, {"name": "Apeks | Copenhagen 2024", "rarity": "💫", "image": "assets/stickers/7306.webp"}, {"name": "Apeks (Glitter) | Copenhagen 2024", "rarity": "👑 Rare", "image": "assets/stickers/7307.webp"}, {"name": "Apeks (Holo) | Copenhagen 2024", "rarity": "🔥", "image": "assets/stickers/7308.webp"}, {"name": "Apeks (Gold) | Copenhagen 2024", "rarity": "👑 Legendary", "image": "assets/stickers/7309.webp"}, {"name": "GamerLegion | Copenhagen 2024", "rarity": "💫", "image": "assets/stickers/7310.webp"}, {"name": "GamerLegion (Glitter) | Copenhagen 2024", "rarity": "👑 Rare", "image": "assets/stickers/7311.webp"}, {"name": "GamerLegion (Holo) | Copenhagen 2024", "rarity": "🔥", "image": "assets/stickers/7312.webp"}, {"name": "GamerLegion (Gold) | Copenhagen 2024", "rarity": "👑 Legendary", "image": "assets/stickers/7313.webp"}, {"name": "SAW | Copenhagen 2024", "rarity": "💫", "image": "assets/stickers/7314.webp"}, {"name": "SAW (Glitter) | Copenhagen 2024", "rarity": "👑 Rare", "image": "assets/stickers/7315.webp"}, {"name": "SAW (Holo) | Copenhagen 2024", "rarity": "🔥", "image": "assets/stickers/7316.webp"}, {"name": "SAW (Gold) | Copenhagen 2024", "rarity": "👑 Legendary", "image": "assets/stickers/7317.webp"}, {"name": "PGL | Copenhagen 2024", "rarity": "💫", "image": "assets/stickers/7350.webp"}, {"name": "PGL (Glitter) | Copenhagen 2024", "rarity": "👑 Rare", "image": "assets/stickers/7351.webp"}, {"name": "PGL (Holo) | Copenhagen 2024", "rarity": "🔥", "image": "assets/stickers/7352.webp"}, {"name": "PGL (Gold) | Copenhagen 2024", "rarity": "👑 Legendary", "image": "assets/stickers/7353.webp"}],
    },
}

STICKER_VALUES = {
    "⭐": 0.10, "✨": 0.50, "💫": 2.00, "🔥": 10.00,
    "👑 Common": 30, "👑 Rare": 75, "👑 Epic": 150, "👑 Legendary": 300
}

# ============================================================
# SLOTS DATA
# ============================================================

SLOT_SYMBOLS = [
    {'emoji': '🍒', 'value': 1,  'name': 'Cherry'},
    {'emoji': '🍋', 'value': 2,  'name': 'Lemon'},
    {'emoji': '🍊', 'value': 3,  'name': 'Orange'},
    {'emoji': '🍇', 'value': 4,  'name': 'Grape'},
    {'emoji': '💎', 'value': 10, 'name': 'Diamond'},
    {'emoji': '7️⃣', 'value': 20, 'name': 'Seven'},
    {'emoji': '🎰', 'value': 50, 'name': 'Jackpot'},
]
SLOT_PAYOUTS = {
    '🍒🍒🍒': 3, '🍋🍋🍋': 5, '🍊🍊🍊': 8,
    '🍇🍇🍇': 12, '💎💎💎': 30, '7️⃣7️⃣7️⃣': 60, '🎰🎰🎰': 200,
}

# ============================================================
# QUEST TYPES
# ============================================================

QUEST_TYPES = {
    "open_cases":   {"name": "🔑 Case Opener",   "base_reward": 500,  "base_required": 5},
    "get_golds":    {"name": "✨ Gold Hunter",    "base_reward": 1000, "base_required": 1},
    "earn_money":   {"name": "💰 Money Maker",   "base_reward": 750,  "base_required": 5000},
    "trade_up":     {"name": "🔄 Trade Master",  "base_reward": 800,  "base_required": 3},
    "sell_items":   {"name": "💸 Salesman",       "base_reward": 600,  "base_required": 5},
    "jackpot_win":  {"name": "🎲 Gambler",        "base_reward": 2000, "base_required": 1},
    "daily_streak": {"name": "📅 Streak Keeper", "base_reward": 1000, "base_required": 5},
}

# ============================================================
# GAME CATALOG  (used by games.html hub)
# ============================================================

GAME_CATALOG = {
    "easy": [
        {"id": "slots",        "name": "Slots",        "emoji": "🎰", "desc": "Spin the reels, match symbols",         "url": "/games/slots.html",        "multiplayer": False},
        {"id": "coinflip",     "name": "Coinflip",     "emoji": "🪙", "desc": "50/50 heads or tails",                  "url": "/games/coinflip.html",     "multiplayer": False},
        {"id": "dice",         "name": "Dice",         "emoji": "🎲", "desc": "Roll the dice, over or under",           "url": "/games/dice.html",         "multiplayer": False},
        {"id": "limbo",        "name": "Limbo",        "emoji": "📉", "desc": "Set a target, beat the multiplier",      "url": "/games/limbo.html",        "multiplayer": False},
        {"id": "hilo",         "name": "Hi-Lo",        "emoji": "🃏", "desc": "Guess higher or lower, chain wins",      "url": "/games/hilo.html",         "multiplayer": False},
        {"id": "dragon-tiger", "name": "Dragon Tiger", "emoji": "🐉", "desc": "Dragon vs Tiger, pick your side",        "url": "/games/dragon-tiger.html", "multiplayer": False},
        {"id": "keno",         "name": "Keno",         "emoji": "🔢", "desc": "Pick your numbers, watch them drop",     "url": "/games/keno.html",         "multiplayer": False},
        {"id": "crash",        "name": "Crash",        "emoji": "🚀", "desc": "Cash out before it crashes — 4 players", "url": "/games/crash.html",        "multiplayer": True},
    ],
    "medium": [
        {"id": "mines",        "name": "Mines",        "emoji": "💣", "desc": "Reveal tiles, avoid the bombs",          "url": "/games/mines.html",        "multiplayer": False},
        {"id": "plinko",       "name": "Plinko",       "emoji": "⚽", "desc": "Drop the ball through the pegs",         "url": "/games/plinko.html",       "multiplayer": False},
        {"id": "tower",        "name": "Tower",        "emoji": "🏗️", "desc": "Climb floors, pick the safe box",        "url": "/games/tower.html",        "multiplayer": False},
        {"id": "shotgun",      "name": "Shotgun",      "emoji": "🔫", "desc": "CS2-themed chamber gamble",              "url": "/games/shotgun.html",      "multiplayer": False},
        {"id": "ladder-climb", "name": "Ladder Climb", "emoji": "🪜", "desc": "Climb higher for bigger rewards",        "url": "/games/ladder-climb.html", "multiplayer": False},
        {"id": "roulette",     "name": "Roulette",     "emoji": "🎡", "desc": "Spin the wheel, place your bets",        "url": "/games/roulette.html",     "multiplayer": False},
    ],
    "hard": [
        {"id": "slide",            "name": "Slide",            "emoji": "🎯", "desc": "Slide into the multiplier zone",         "url": "/games/slide.html",            "multiplayer": False},
        {"id": "mystery-box",      "name": "Mystery Box",      "emoji": "📦", "desc": "CS2 boxes: multipliers or bombs",        "url": "/games/mystery-box.html",      "multiplayer": False},
        {"id": "russian-roulette", "name": "Russian Roulette", "emoji": "🔴", "desc": "You vs an AI with attitude",             "url": "/games/russian-roulette.html", "multiplayer": False},
        {"id": "baccarat",         "name": "Baccarat",         "emoji": "🃏", "desc": "Player vs Banker, closest to 9 wins",    "url": "/games/baccarat.html",         "multiplayer": False},
        {"id": "blackjack",        "name": "Blackjack",        "emoji": "🂡", "desc": "Beat the dealer, hit 21",                "url": "/games/blackjack.html",        "multiplayer": False},
    ],
    "heavy": [
        {"id": "live-race", "name": "Live Race", "emoji": "🏃", "desc": "CS2 agents race — 4 players + bots",   "url": "/games/live-race.html", "multiplayer": True},
        {"id": "battles",   "name": "Case Battles","emoji": "⚔️","desc": "Open cases PvP — 4 players + bots",   "url": "/battle-setup.html",    "multiplayer": True},
    ],
    "featured": [
        {"id": "poker", "name": "Poker", "emoji": "♠️", "desc": "Texas Hold'em or Video Poker — 4 players", "url": "/games/poker.html", "multiplayer": True},
    ],
}

# ============================================================
# FLOAT / CONDITION HELPERS
# ============================================================

def generate_skin_float() -> float:
    return round(random.uniform(0.00, 1.00), 4)

def get_skin_condition(float_value: float) -> str:
    if float_value <= 0.07:   return "Factory New"
    elif float_value <= 0.15: return "Minimal Wear"
    elif float_value <= 0.38: return "Field-Tested"
    elif float_value <= 0.45: return "Well-Worn"
    else:                     return "Battle-Scarred"

# ============================================================
# VALUE CALCULATION
# ============================================================

def calculate_item_value(
    rarity: str,
    condition: Optional[str] = None,
    tier: Optional[str] = None,
    is_stattrak: bool = False,
) -> float:
    try:
        if rarity == "Gold" and tier:
            base_value = float(GOLD_VALUES.get(tier, 150))
        elif rarity in WEAPON_BASE_VALUES:
            base_value = float(WEAPON_BASE_VALUES[rarity])
        else:
            base_value = 0.25
        multiplier = float(CONDITION_MULTIPLIERS.get(condition or "Field-Tested", 1.0))
        value = base_value * multiplier
        if is_stattrak:
            value *= 2.0
        return round(value, 2)
    except Exception:
        return 0.25

# ============================================================
# ITEM GENERATION
# ============================================================

def get_random_item(case_id: str) -> Optional[Dict]:
    """Roll a random item from a case using CS2 drop rates."""
    case = CASES.get(case_id)
    if not case or not case.get('items'):
        return None

    rand = random.random() * 100
    cumulative = 0.0
    selected_rarity: Optional[str] = None

    for rarity, chance in DROP_RATES.items():
        cumulative += chance
        if rand <= cumulative:
            selected_rarity = rarity
            break

    if not selected_rarity:
        selected_rarity = "Blue"

    possible = [i for i in case['items'] if i['rarity'] == selected_rarity]
    if not possible:
        possible = case['items']

    item = random.choice(possible)
    is_stattrak = random.random() < 0.1
    float_value = generate_skin_float()
    condition = get_skin_condition(float_value)
    tier = item.get('tier')
    value = calculate_item_value(selected_rarity, condition, tier, is_stattrak)

    raw_name = item['name'].replace('StatTrak™ ', '').replace('StatTrak™', '').strip()
    name = f"StatTrak™ {raw_name}" if is_stattrak else raw_name
    rarity_emoji = RARITY_EMOJIS.get(selected_rarity, "")

    return {
        'name':         name,
        'display_name': f"{rarity_emoji} {name}",
        'rarity':       selected_rarity,
        'rarity_emoji': rarity_emoji,
        'tier':         tier,
        'condition':    condition,
        'float':        float_value,
        'price':        value,
        'is_stattrak':  is_stattrak,
    }

def get_random_sticker(capsule_id: str) -> Optional[Dict]:
    capsule = STICKER_CAPSULES.get(capsule_id)
    if not capsule or not capsule.get('stickers'):
        return None
    sticker = random.choice(capsule['stickers'])
    is_stattrak = random.random() < 0.1
    value = STICKER_VALUES.get(sticker['rarity'], 0.25)
    if is_stattrak:
        value *= 2.0
    name = f"StatTrak™ {sticker['name']}" if is_stattrak else sticker['name']
    image = sticker.get('image', '')
    return {
        'name':         name,
        'display_name': name,
        'rarity':       sticker['rarity'],
        'price':        round(value, 2),
        'is_stattrak':  is_stattrak,
        'image':        image,
    }

# ============================================================
# WEAPON IMAGE PATH
# ============================================================

def get_weapon_image_path(item_name: str, weapon_dir: Optional[str] = None) -> str:
    if weapon_dir is None:
        weapon_dir = "static/images/Organized_Weapons_with_Skins"
    fallback = os.path.join("static/images/Default CS2 Weapons", "weapon_ak47.png")
    clean = re.sub(r'StatTrak™\s*|★\s*', '', item_name).strip()
    # Future: walk weapon_dir to find actual file; for now return fallback
    return fallback

# ============================================================
# JSON SERIALISATION HELPER
# ============================================================

from decimal import Decimal

def convert_decimals(obj: Any) -> Any:
    """Recursively convert Decimal → float for JSON serialisation."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: convert_decimals(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [convert_decimals(v) for v in obj]
    return obj

# ============================================================
# CRASH MULTIPLIER MATH
# ============================================================

def generate_crash_point(house_edge: float = 0.04) -> float:
    """
    Generate a provably-fair crash point.
    house_edge of 0.04 means 4% house edge.
    Returns a float >= 1.00.
    """
    r = random.random()
    if r < house_edge:
        return 1.00  # instant crash
    crash = (1.0 - house_edge) / (1.0 - r)
    return round(max(1.00, crash), 2)

def crash_multiplier_at_second(elapsed: float, speed: float = 0.06) -> float:
    """
    Exponential multiplier growth: starts at 1.00, grows over time.
    elapsed = seconds since round start
    """
    return round(math.e ** (speed * elapsed), 2)

# ============================================================
# USER HELPERS
# ============================================================

async def ensure_user_exists(user_id: int, conn=None) -> None:
    """Create user row if it doesn't exist yet."""
    pool = await get_db()
    if conn:
        await _ensure_user(user_id, conn)
    else:
        async with pool.acquire() as c:
            await _ensure_user(user_id, c)

async def _ensure_user(user_id: int, conn) -> None:
    await conn.execute("""
        INSERT INTO users (user_id, balance, created_at, updated_at)
        VALUES ($1, 1000, NOW(), NOW())
        ON CONFLICT (user_id) DO NOTHING
    """, user_id)

async def get_user_balance(user_id: int) -> float:
    pool = await get_db()
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            "SELECT balance FROM users WHERE user_id = $1", user_id
        )
    return float(val or 0)

async def deduct_balance(user_id: int, amount: float, conn=None) -> bool:
    """Deduct amount from user balance. Returns False if insufficient funds."""
    pool = await get_db()
    async def _do(c):
        result = await c.execute("""
            UPDATE users SET balance = balance - $1, updated_at = NOW()
            WHERE user_id = $2 AND balance >= $1
        """, amount, user_id)
        return result == "UPDATE 1"
    if conn:
        return await _do(conn)
    async with pool.acquire() as c:
        return await _do(c)

async def add_balance(user_id: int, amount: float, conn=None) -> None:
    pool = await get_db()
    async def _do(c):
        await c.execute("""
            UPDATE users SET balance = balance + $1, updated_at = NOW()
            WHERE user_id = $2
        """, amount, user_id)
    if conn:
        await _do(conn)
    else:
        async with pool.acquire() as c:
            await _do(c)

# ============================================================
# WEBSOCKET BROADCAST HELPER
# ============================================================

async def broadcast_to_set(ws_set: Set, message: dict) -> Set:
    """
    Broadcast a JSON message to all WebSockets in ws_set.
    Returns a set of dead connections that should be removed.
    Always use try/except — never rely on ws.closed.
    """
    dead = set()
    for ws in ws_set:
        try:
            await ws.send_json(message)
        except Exception:
            dead.add(ws)
    return dead
