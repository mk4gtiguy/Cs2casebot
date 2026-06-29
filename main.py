import discord
from discord.ext import commands
from discord import app_commands
import os
import asyncpg
import random
import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from dotenv import load_dotenv
from typing import Optional

# Secure RNG helpers (Fix 1)
from shared import secure_random, secure_randint, secure_choice, secure_shuffle, deduct_balance

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if os.path.exists('.env'):
    load_dotenv()

TOKEN = os.getenv('DISCORD_BOT_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')

# ============================================
# CHANNEL CONFIGURATION
# ============================================

SUPPORT_CHANNEL_ID = 1516670656266113085
BOT_CHANNEL_ID = SUPPORT_CHANNEL_ID

# ============================================
# OTHER CONFIG
# ============================================

KO_FI_URL = "https://ko-fi.com/mk4gtiguy"
DASHBOARD_URL = "https://cs2casebot.xyz/"
DISCORD_INVITE_URL = "https://discord.gg/mU33pc7TDE"

bot = commands.Bot(command_prefix='!', intents=discord.Intents.all())
db_pool = None

# ── Shared module integration ─────────────────────────────────
# This lets admin.py DM users through the Discord bot.
try:
    import shared as _shared

    async def _bot_notify(user_id: int, message: str):
        """Send a Discord DM — called by the web server's admin routes."""
        try:
            user = await bot.fetch_user(user_id)
            await user.send(message)
        except Exception as e:
            logger.warning(f"bot_notify failed for {user_id}: {e}")

    _shared.bot_notify = _bot_notify
except ImportError:
    pass  # shared.py not present — web server not running alongside

# Fix 3: Jackpot state is now DB-backed — remove in-memory globals.
# jackpot_pot = 0        ← REMOVED
# jackpot_entries = []   ← REMOVED
# jackpot_lock = asyncio.Lock()  ← keep for I/O serialisation only
jackpot_lock = asyncio.Lock()

# Fix 3: DB-backed jackpot helpers
async def jackpot_enter(user_id: int, amount: float):
    """Deduct balance and add to jackpot pot — all in one transaction."""
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            result = await conn.execute(
                "UPDATE users SET balance = balance - $1 WHERE user_id = $2 AND balance >= $1",
                amount, user_id
            )
            if result == "UPDATE 0":
                return False   # insufficient balance
            await conn.execute(
                "UPDATE jackpot_state SET pot = pot + $1, updated_at = NOW() WHERE id = 1",
                amount
            )
            await conn.execute(
                "INSERT INTO jackpot_entries (user_id, amount) VALUES ($1, $2)",
                user_id, amount
            )
    return True

async def jackpot_draw() -> tuple:
    """Pick winner weighted by entry amount, clear state. Returns (winner_id, pot)."""
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            entries = await conn.fetch("SELECT user_id, amount FROM jackpot_entries")
            pot = await conn.fetchval("SELECT pot FROM jackpot_state WHERE id = 1") or 0
            if not entries:
                return None, 0, 0
            # Weighted selection using secure RNG
            total = sum(float(e['amount']) for e in entries)
            pick = secure_random() * total
            cumulative = 0.0
            winner_id = entries[-1]['user_id']
            for e in entries:
                cumulative += float(e['amount'])
                if pick <= cumulative:
                    winner_id = e['user_id']
                    break
            win_amount = int(float(pot) * 0.95)
            await conn.execute("UPDATE jackpot_state SET pot = 0 WHERE id = 1")
            await conn.execute("DELETE FROM jackpot_entries")
            await conn.execute(
                "UPDATE users SET balance = balance + $1 WHERE user_id = $2",
                win_amount, winner_id
            )
            return winner_id, win_amount, float(pot)

# ============================================
# CHANNEL PERMISSION CHECK
# ============================================

async def is_bot_channel(interaction: discord.Interaction):
    if not interaction.guild:
        return True
    try:
        async with db_pool.acquire() as conn:
            setting = await conn.fetchrow("""
                SELECT bot_channel_id FROM guild_settings WHERE guild_id = $1
            """, interaction.guild_id)
        if not setting or setting['bot_channel_id'] is None:
            return True
        if interaction.channel_id != setting['bot_channel_id']:
            await interaction.response.send_message(
                f"❌ Please use bot commands in <#{setting['bot_channel_id']}>!",
                ephemeral=True
            )
            return False
        return True
    except Exception as e:
        logger.error(f"is_bot_channel error: {e}")
        return True

# ============================================
# EMOJIS
# ============================================

CASE_EMOJIS = {
    "cs:go_weapon_case": "📦",
    "esports_2013_case": "🎯",
    "operation_phoenix_weapon_case": "⚡",
    "huntsman_weapon_case": "🔥",
    "operation_breakout_weapon_case": "💎",
    "esports_2014_summer_case": "🌟",
    "operation_vanguard_weapon_case": "🎨",
    "chroma_case": "🌈",
    "chroma_2_case": "💥",
    "falchion_case": "🌅",
    "shadow_case": "⚠️",
    "revolver_case": "🤲",
    "operation_wildfire_case": "🎪",
    "chroma_3_case": "🏹",
    "gamma_case": "🗡️",
    "gamma_2_case": "🛡️",
    "glove_case": "👑",
    "spectrum_case": "🎰",
    "operation_hydra_case": "🎲",
    "spectrum_2_case": "🎳",
    "clutch_case": "🎭",
    "horizon_case": "🎪",
    "danger_zone_case": "🎯",
    "prisma_case": "🎱",
    "shattered_web_case": "🔫",
    "cs20_case": "🌙",
    "prisma_2_case": "🎂",
    "fracture_case": "💎",
    "operation_broken_fang_case": "⚡",
    "snakebite_case": "🌊",
    "operation_riptide_case": "🌪️",
    "dreams_and_nightmares_case": "🎇",
    "recoil_case": "📦",
    "revolution_case": "🎯",
    "kilowatt_case": "⚡",
    "gallery_case": "🔥",
    "fever_case": "💎"
}

CAPSULE_EMOJIS = {
    "recoil": "⭐", "dreams": "🌙⭐", "cs20": "🎂⭐",
    "championship": "🏆", "legends": "👑"
}

RARITY_EMOJIS = {
    "Blue": "🟦",
    "Purple": "🟪",
    "Pink": "💗",
    "Red": "🔴",
    "Gold": "⭐"
}

# ============================================
# PRICING DATA
# ============================================

WEAPON_BASE_VALUES = {"Blue": 0.25, "Purple": 1.00, "Pink": 4.00, "Red": 20.00}
GOLD_VALUES = {"Common": 150, "Rare": 300, "Epic": 600, "Legendary": 1000, "Mythic": 2500}
CONDITION_MULTIPLIERS = {"Factory New": 2.0, "Minimal Wear": 1.5, "Field-Tested": 1.0, "Well-Worn": 0.75, "Battle-Scarred": 0.5}
STICKER_VALUES = {"⭐": 0.10, "✨": 0.50, "💫": 2.00, "🔥": 10.00, "👑 Common": 30, "👑 Rare": 75, "👑 Epic": 150, "👑 Legendary": 300}
DROP_RATES = {"Gold": 2.6, "Red": 2.5, "Pink": 2.5, "Purple": 5.0, "Blue": 87.4}

TRADE_UP_PROGRESSION = {"Blue": "Purple", "Purple": "Pink", "Pink": "Red", "Red": "Gold"}
GOLD_TIER_PROGRESSION = ["Common", "Rare", "Epic", "Legendary", "Mythic"]
STICKER_TRADE_PROGRESSION = {"⭐": "✨", "✨": "💫", "💫": "🔥", "🔥": "👑 Common", "👑 Common": "👑 Rare", "👑 Rare": "👑 Epic", "👑 Epic": "👑 Legendary"}

QUEST_TYPES = {
    "open_cases": {"name": "🔑 Case Opener", "base_reward": 500, "base_required": 5},
    "get_golds": {"name": "✨ Gold Hunter", "base_reward": 1000, "base_required": 1},
    "earn_money": {"name": "💰 Money Maker", "base_reward": 750, "base_required": 5000},
    "trade_up": {"name": "🔄 Trade Master", "base_reward": 800, "base_required": 3},
    "sell_items": {"name": "💸 Salesman", "base_reward": 600, "base_required": 5},
    "jackpot_win": {"name": "🎲 Gambler", "base_reward": 2000, "base_required": 1},
    "daily_streak": {"name": "📅 Streak Keeper", "base_reward": 1000, "base_required": 5}
}

# ============================================
# FLOAT SYSTEM
# ============================================

def generate_skin_float():
    return round(secure_random(), 4)

def get_skin_condition(float_value):
    if float_value <= 0.07:
        return "Factory New"
    elif float_value <= 0.15:
        return "Minimal Wear"
    elif float_value <= 0.38:
        return "Field-Tested"
    elif float_value <= 0.45:
        return "Well-Worn"
    else:
        return "Battle-Scarred"

# ============================================
# CASES DATA - 37 REAL CS2 CASES!
# ============================================

CASES = {
    "cs:go_weapon_case": {
        "name": "CS:GO Weapon Case",
        "emoji": "📦",
        "price": 2.0,
        "items": [
            {"name": "MP7 | Skulls", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "AUG | Wings", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "SG 553 | Ultraviolet", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "Glock-18 | Dragon Tattoo", "rarity": "Purple", "condition": "Well-Worn"},
            {"name": "USP-S | Dark Water", "rarity": "Purple", "condition": "Well-Worn"},
            {"name": "M4A1-S | Dark Water", "rarity": "Purple", "condition": "Battle-Scarred"},
            {"name": "AK-47 | Case Hardened", "rarity": "Pink", "condition": "Well-Worn"},
            {"name": "Desert Eagle | Hypnotic", "rarity": "Pink", "condition": "Minimal Wear"},
            {"name": "★ Bayonet", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Fade", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Slaughter", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"}
        ]
    },
    "esports_2013_case": {
        "name": "eSports 2013 Case",
        "emoji": "🎯",
        "price": 2.0,
        "items": [
            {"name": "M4A4 | Faded Zebra", "rarity": "Blue", "condition": "Factory New"},
            {"name": "MAG-7 | Memento", "rarity": "Blue", "condition": "Minimal Wear"},
            {"name": "FAMAS | Doomkitty", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "Galil AR | Orange DDPAT", "rarity": "Purple", "condition": "Well-Worn"},
            {"name": "Sawed-Off | Orange DDPAT", "rarity": "Purple", "condition": "Well-Worn"},
            {"name": "P250 | Splash", "rarity": "Purple", "condition": "Field-Tested"},
            {"name": "AK-47 | Red Laminate", "rarity": "Pink", "condition": "Factory New"},
            {"name": "AWP | BOOM", "rarity": "Pink", "condition": "Factory New"},
            {"name": "★ Bayonet", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Fade", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Slaughter", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"}
        ]
    },
    "operation_phoenix_weapon_case": {
        "name": "Operation Phoenix Weapon Case",
        "emoji": "⚡",
        "price": 2.5,
        "items": [
            {"name": "UMP-45 | Corporal", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "Negev | Terrain", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "Tec-9 | Sandstorm", "rarity": "Blue", "condition": "Factory New"},
            {"name": "MAG-7 | Heaven Guard", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "MAC-10 | Heat", "rarity": "Purple", "condition": "Battle-Scarred"},
            {"name": "SG 553 | Pulse", "rarity": "Purple", "condition": "Minimal Wear"},
            {"name": "FAMAS | Sergeant", "rarity": "Purple", "condition": "Battle-Scarred"},
            {"name": "USP-S | Guardian", "rarity": "Purple", "condition": "Field-Tested"},
            {"name": "★ Bayonet", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Fade", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Slaughter", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"}
        ]
    },
    "huntsman_weapon_case": {
        "name": "Huntsman Weapon Case",
        "emoji": "🔥",
        "price": 2.5,
        "items": [
            {"name": "Tec-9 | Isaac", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "SSG 08 | Slashed", "rarity": "Blue", "condition": "Minimal Wear"},
            {"name": "Galil AR | Kami", "rarity": "Blue", "condition": "Factory New"},
            {"name": "CZ75-Auto | Twist", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "P90 | Module", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "P2000 | Pulse", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "AUG | Torque", "rarity": "Purple", "condition": "Minimal Wear"},
            {"name": "PP-Bizon | Antique", "rarity": "Purple", "condition": "Minimal Wear"},
            {"name": "★ Huntsman Knife", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Huntsman Knife | Fade", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Huntsman Knife | Crimson Web", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"}
        ]
    },
    "operation_breakout_weapon_case": {
        "name": "Operation Breakout Weapon Case",
        "emoji": "💎",
        "price": 2.5,
        "items": [
            {"name": "MP7 | Urban Hazard", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "Negev | Desert-Strike", "rarity": "Blue", "condition": "Factory New"},
            {"name": "P2000 | Ivory", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "SSG 08 | Abyss", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "UMP-45 | Labyrinth", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "PP-Bizon | Osiris", "rarity": "Purple", "condition": "Field-Tested"},
            {"name": "CZ75-Auto | Tigris", "rarity": "Purple", "condition": "Factory New"},
            {"name": "Nova | Koi", "rarity": "Purple", "condition": "Field-Tested"},
            {"name": "★ Butterfly Knife", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Butterfly Knife | Fade", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Butterfly Knife | Crimson Web", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"}
        ]
    },
    "esports_2014_summer_case": {
        "name": "eSports 2014 Summer Case",
        "emoji": "🌟",
        "price": 2.0,
        "items": [
            {"name": "SSG 08 | Dark Water", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "MAC-10 | Ultraviolet", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "USP-S | Blood Tiger", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "CZ75-Auto | Hexane", "rarity": "Blue", "condition": "Factory New"},
            {"name": "Negev | Bratatat", "rarity": "Blue", "condition": "Minimal Wear"},
            {"name": "XM1014 | Red Python", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "PP-Bizon | Blue Streak", "rarity": "Purple", "condition": "Minimal Wear"},
            {"name": "P90 | Virus", "rarity": "Purple", "condition": "Well-Worn"},
            {"name": "★ Bayonet", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Fade", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Slaughter", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"}
        ]
    },
    "operation_vanguard_weapon_case": {
        "name": "Operation Vanguard Weapon Case",
        "emoji": "🎨",
        "price": 2.5,
        "items": [
            {"name": "G3SG1 | Murky", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "MAG-7 | Firestarter", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "MP9 | Dart", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "Five-SeveN | Urban Hazard", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "UMP-45 | Delusion", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "Glock-18 | Grinder", "rarity": "Purple", "condition": "Well-Worn"},
            {"name": "M4A1-S | Basilisk", "rarity": "Purple", "condition": "Well-Worn"},
            {"name": "M4A4 | Griffin", "rarity": "Purple", "condition": "Factory New"},
            {"name": "★ Bayonet", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Fade", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Slaughter", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"}
        ]
    },
    "chroma_case": {
        "name": "Chroma Case",
        "emoji": "🌈",
        "price": 2.0,
        "items": [
            {"name": "Glock-18 | Catacombs", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "M249 | System Lock", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "MP9 | Deadly Poison", "rarity": "Blue", "condition": "Factory New"},
            {"name": "SCAR-20 | Grotto", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "XM1014 | Quicksilver", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "Dual Berettas | Urban Shock", "rarity": "Purple", "condition": "Field-Tested"},
            {"name": "Desert Eagle | Naga", "rarity": "Purple", "condition": "Factory New"},
            {"name": "MAC-10 | Malachite", "rarity": "Purple", "condition": "Minimal Wear"},
            {"name": "★ Bayonet | Marble Fade", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Tiger Tooth", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Doppler", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"}
        ]
    },
    "chroma_2_case": {
        "name": "Chroma 2 Case",
        "emoji": "💥",
        "price": 2.0,
        "items": [
            {"name": "AK-47 | Elite Build", "rarity": "Blue", "condition": "Minimal Wear"},
            {"name": "MP7 | Armor Core", "rarity": "Blue", "condition": "Factory New"},
            {"name": "Desert Eagle | Bronze Deco", "rarity": "Blue", "condition": "Minimal Wear"},
            {"name": "P250 | Valence", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "Negev | Man-o'-war", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "Sawed-Off | Origami", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "AWP | Worm God", "rarity": "Purple", "condition": "Factory New"},
            {"name": "MAG-7 | Heat", "rarity": "Purple", "condition": "Field-Tested"},
            {"name": "★ Bayonet | Marble Fade", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Tiger Tooth", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Doppler", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"}
        ]
    },
    "falchion_case": {
        "name": "Falchion Case",
        "emoji": "🌅",
        "price": 2.0,
        "items": [
            {"name": "Galil AR | Rocket Pop", "rarity": "Blue", "condition": "Minimal Wear"},
            {"name": "Glock-18 | Bunsen Burner", "rarity": "Blue", "condition": "Factory New"},
            {"name": "Nova | Ranger", "rarity": "Blue", "condition": "Factory New"},
            {"name": "P90 | Elite Build", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "UMP-45 | Riot", "rarity": "Blue", "condition": "Minimal Wear"},
            {"name": "USP-S | Torque", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "FAMAS | Neural Net", "rarity": "Purple", "condition": "Battle-Scarred"},
            {"name": "M4A4 | Evil Daimyo", "rarity": "Purple", "condition": "Battle-Scarred"},
            {"name": "★ Falchion Knife", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Falchion Knife | Fade", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Falchion Knife | Crimson Web", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"}
        ]
    },
    "shadow_case": {
        "name": "Shadow Case",
        "emoji": "⚠️",
        "price": 2.0,
        "items": [
            {"name": "Dual Berettas | Dualing Dragons", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "FAMAS | Survivor Z", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "Glock-18 | Wraiths", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "MAC-10 | Rangeen", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "MAG-7 | Cobalt Core", "rarity": "Blue", "condition": "Factory New"},
            {"name": "SCAR-20 | Green Marine", "rarity": "Blue", "condition": "Minimal Wear"},
            {"name": "XM1014 | Scumbria", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "Galil AR | Stone Cold", "rarity": "Purple", "condition": "Minimal Wear"},
            {"name": "★ Shadow Daggers", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Shadow Daggers | Fade", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Shadow Daggers | Crimson Web", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"}
        ]
    },
    "revolver_case": {
        "name": "Revolver Case",
        "emoji": "🤲",
        "price": 2.0,
        "items": [
            {"name": "R8 Revolver | Crimson Web", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "AUG | Ricochet", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "Desert Eagle | Corinthian", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "P2000 | Imperial", "rarity": "Blue", "condition": "Factory New"},
            {"name": "Sawed-Off | Yorick", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "SCAR-20 | Outbreak", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "PP-Bizon | Fuel Rod", "rarity": "Purple", "condition": "Factory New"},
            {"name": "Five-SeveN | Retrobution", "rarity": "Purple", "condition": "Battle-Scarred"},
            {"name": "★ Bayonet", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Fade", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Slaughter", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"}
        ]
    },
    "operation_wildfire_case": {
        "name": "Operation Wildfire Case",
        "emoji": "🎪",
        "price": 3.0,
        "items": [
            {"name": "PP-Bizon | Photic Zone", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "Dual Berettas | Cartel", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "MAC-10 | Lapis Gator", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "SSG 08 | Necropos", "rarity": "Blue", "condition": "Factory New"},
            {"name": "Tec-9 | Jambiya", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "USP-S | Lead Conduit", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "FAMAS | Valence", "rarity": "Purple", "condition": "Minimal Wear"},
            {"name": "Five-SeveN | Triumvirate", "rarity": "Purple", "condition": "Minimal Wear"},
            {"name": "★ Bowie Knife", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bowie Knife | Fade", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bowie Knife | Crimson Web", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"}
        ]
    },
    "chroma_3_case": {
        "name": "Chroma 3 Case",
        "emoji": "🏹",
        "price": 2.0,
        "items": [
            {"name": "Dual Berettas | Ventilators", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "G3SG1 | Orange Crash", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "M249 | Spectre", "rarity": "Blue", "condition": "Factory New"},
            {"name": "MP9 | Bioleak", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "P2000 | Oceanic", "rarity": "Blue", "condition": "Factory New"},
            {"name": "Sawed-Off | Fubar", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "SG 553 | Atlas", "rarity": "Blue", "condition": "Factory New"},
            {"name": "CZ75-Auto | Red Astor", "rarity": "Purple", "condition": "Field-Tested"},
            {"name": "★ Bayonet | Marble Fade", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Tiger Tooth", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Doppler", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"}
        ]
    },
    "gamma_case": {
        "name": "Gamma Case",
        "emoji": "🗡️",
        "price": 2.5,
        "items": [
            {"name": "Five-SeveN | Violent Daimyo", "rarity": "Blue", "condition": "Factory New"},
            {"name": "MAC-10 | Carnivore", "rarity": "Blue", "condition": "Minimal Wear"},
            {"name": "Nova | Exo", "rarity": "Blue", "condition": "Minimal Wear"},
            {"name": "P250 | Iron Clad", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "PP-Bizon | Harvester", "rarity": "Blue", "condition": "Factory New"},
            {"name": "SG 553 | Aerial", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "Tec-9 | Ice Cap", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "AUG | Aristocrat", "rarity": "Purple", "condition": "Field-Tested"},
            {"name": "★ Bayonet | Gamma Doppler", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Gamma Doppler", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Gamma Doppler", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"}
        ]
    },
    "gamma_2_case": {
        "name": "Gamma 2 Case",
        "emoji": "🛡️",
        "price": 2.5,
        "items": [
            {"name": "CZ75-Auto | Imprint", "rarity": "Blue", "condition": "Factory New"},
            {"name": "Five-SeveN | Scumbria", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "G3SG1 | Ventilator", "rarity": "Blue", "condition": "Factory New"},
            {"name": "Negev | Dazzle", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "P90 | Grim", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "UMP-45 | Briefing", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "XM1014 | Slipstream", "rarity": "Blue", "condition": "Factory New"},
            {"name": "Desert Eagle | Directive", "rarity": "Purple", "condition": "Minimal Wear"},
            {"name": "★ Bayonet | Gamma Doppler", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Gamma Doppler", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bayonet | Gamma Doppler", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"}
        ]
    },
    "glove_case": {
        "name": "Glove Case",
        "emoji": "👑",
        "price": 4.0,
        "items": [
            {"name": "CZ75-Auto | Polymer", "rarity": "Blue", "condition": "Factory New"},
            {"name": "Glock-18 | Ironwork", "rarity": "Blue", "condition": "Minimal Wear"},
            {"name": "MP7 | Cirrus", "rarity": "Blue", "condition": "Factory New"},
            {"name": "Galil AR | Black Sand", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "MP9 | Sand Scale", "rarity": "Blue", "condition": "Factory New"},
            {"name": "MAG-7 | Sonar", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "P2000 | Turf", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "Dual Berettas | Royal Consorts", "rarity": "Purple", "condition": "Factory New"},
            {"name": "★ Bloodhound Gloves | Snakebite", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bloodhound Gloves | Bronzed", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bloodhound Gloves | Charred", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"}
        ]
    },
    "spectrum_case": {
        "name": "Spectrum Case",
        "emoji": "🎰",
        "price": 2.5,
        "items": [
            {"name": "PP-Bizon | Jungle Slipstream", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "SCAR-20 | Blueprint", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "Desert Eagle | Oxide Blaze", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "Five-SeveN | Capillary", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "MP7 | Akoben", "rarity": "Blue", "condition": "Minimal Wear"},
            {"name": "P250 | Ripple", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "Sawed-Off | Zander", "rarity": "Blue", "condition": "Minimal Wear"},
            {"name": "Galil AR | Crimson Tsunami", "rarity": "Purple", "condition": "Field-Tested"},
            {"name": "★ Bowie Knife | Marble Fade", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bowie Knife | Tiger Tooth", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bowie Knife | Doppler", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"}
        ]
    },
    "operation_hydra_case": {
        "name": "Operation Hydra Case",
        "emoji": "🎲",
        "price": 4.0,
        "items": [
            {"name": "USP-S | Blueprint", "rarity": "Blue", "condition": "Minimal Wear"},
            {"name": "FAMAS | Macabre", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "M4A1-S | Briefing", "rarity": "Blue", "condition": "Factory New"},
            {"name": "MAC-10 | Aloha", "rarity": "Blue", "condition": "Factory New"},
            {"name": "MAG-7 | Hard Water", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "Tec-9 | Cut Out", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "UMP-45 | Metal Flowers", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "AK-47 | Orbit Mk01", "rarity": "Purple", "condition": "Minimal Wear"},
            {"name": "★ Bloodhound Gloves | Snakebite", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bloodhound Gloves | Bronzed", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bloodhound Gloves | Charred", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"}
        ]
    },
    "spectrum_2_case": {
        "name": "Spectrum 2 Case",
        "emoji": "🎳",
        "price": 3.0,
        "items": [
            {"name": "Sawed-Off | Morris", "rarity": "Blue", "condition": "Minimal Wear"},
            {"name": "AUG | Triqua", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "G3SG1 | Hunter", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "Glock-18 | Off World", "rarity": "Blue", "condition": "Factory New"},
            {"name": "MAC-10 | Oceanic", "rarity": "Blue", "condition": "Factory New"},
            {"name": "Tec-9 | Cracked Opal", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "SCAR-20 | Jungle Slipstream", "rarity": "Blue", "condition": "Minimal Wear"},
            {"name": "MP9 | Goo", "rarity": "Purple", "condition": "Factory New"},
            {"name": "★ Bowie Knife | Marble Fade", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bowie Knife | Tiger Tooth", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bowie Knife | Doppler", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"}
        ]
    },
    "clutch_case": {
        "name": "Clutch Case",
        "emoji": "🎭",
        "price": 3.0,
        "items": [
            {"name": "PP-Bizon | Night Riot", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "Five-SeveN | Flame Test", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "MP9 | Black Sand", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "P2000 | Urban Hazard", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "R8 Revolver | Grip", "rarity": "Blue", "condition": "Minimal Wear"},
            {"name": "SG 553 | Aloha", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "XM1014 | Oxide Blaze", "rarity": "Blue", "condition": "Minimal Wear"},
            {"name": "Glock-18 | Moonrise", "rarity": "Purple", "condition": "Well-Worn"},
            {"name": "★ Driver Gloves | Imperial Plaid", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Driver Gloves | King Snake", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Driver Gloves | Racing Green", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"}
        ]
    },
    "horizon_case": {
        "name": "Horizon Case",
        "emoji": "🎪",
        "price": 2.5,
        "items": [
            {"name": "AUG | Amber Slipstream", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "Dual Berettas | Shred", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "Glock-18 | Warhawk", "rarity": "Blue", "condition": "Minimal Wear"},
            {"name": "MP9 | Capillary", "rarity": "Blue", "condition": "Minimal Wear"},
            {"name": "P90 | Traction", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "R8 Revolver | Survivalist", "rarity": "Blue", "condition": "Factory New"},
            {"name": "Tec-9 | Snek-9", "rarity": "Blue", "condition": "Minimal Wear"},
            {"name": "CZ75-Auto | Eco", "rarity": "Purple", "condition": "Factory New"},
            {"name": "★ Navaja Knife", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Navaja Knife | Fade", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Navaja Knife | Crimson Web", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"}
        ]
    },
    "danger_zone_case": {
        "name": "Danger Zone Case",
        "emoji": "🎯",
        "price": 2.5,
        "items": [
            {"name": "MP9 | Modest Threat", "rarity": "Blue", "condition": "Minimal Wear"},
            {"name": "Glock-18 | Oxide Blaze", "rarity": "Blue", "condition": "Factory New"},
            {"name": "Nova | Wood Fired", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "M4A4 | Magnesium", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "Sawed-Off | Black Sand", "rarity": "Blue", "condition": "Minimal Wear"},
            {"name": "SG 553 | Danger Close", "rarity": "Blue", "condition": "Minimal Wear"},
            {"name": "Tec-9 | Fubar", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "G3SG1 | Scavenger", "rarity": "Purple", "condition": "Minimal Wear"},
            {"name": "★ Navaja Knife", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Navaja Knife | Fade", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Navaja Knife | Crimson Web", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"}
        ]
    },
    "prisma_case": {
        "name": "Prisma Case",
        "emoji": "🎱",
        "price": 2.5,
        "items": [
            {"name": "FAMAS | Crypsis", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "AK-47 | Uncharted", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "MAC-10 | Whitefish", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "Galil AR | Akoben", "rarity": "Blue", "condition": "Minimal Wear"},
            {"name": "MP7 | Mischief", "rarity": "Blue", "condition": "Factory New"},
            {"name": "P250 | Verdigris", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "P90 | Off World", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "AWP | Atheris", "rarity": "Purple", "condition": "Factory New"},
            {"name": "★ Navaja Knife", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Navaja Knife | Marble Fade", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Navaja Knife | Tiger Tooth", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"}
        ]
    },
    "shattered_web_case": {
        "name": "Shattered Web Case",
        "emoji": "🔫",
        "price": 4.0,
        "items": [
            {"name": "MP5-SD | Acid Wash", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "Nova | Plume", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "G3SG1 | Black Sand", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "R8 Revolver | Memento", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "Dual Berettas | Balance", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "SCAR-20 | Torn", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "M249 | Warbird", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "PP-Bizon | Embargo", "rarity": "Purple", "condition": "Minimal Wear"},
            {"name": "★ Nomad Knife", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Nomad Knife | Fade", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Nomad Knife | Crimson Web", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"}
        ]
    },
    "cs20_case": {
        "name": "CS20 Case",
        "emoji": "🌙",
        "price": 2.5,
        "items": [
            {"name": "Dual Berettas | Elite 1.6", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "Tec-9 | Flash Out", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "MAC-10 | Classic Crate", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "MAG-7 | Popdog", "rarity": "Blue", "condition": "Factory New"},
            {"name": "SCAR-20 | Assault", "rarity": "Blue", "condition": "Minimal Wear"},
            {"name": "FAMAS | Decommissioned", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "Glock-18 | Sacrifice", "rarity": "Blue", "condition": "Factory New"},
            {"name": "M249 | Aztec", "rarity": "Purple", "condition": "Battle-Scarred"},
            {"name": "★ Classic Knife", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Classic Knife | Fade", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Classic Knife | Crimson Web", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"}
        ]
    },
    "prisma_2_case": {
        "name": "Prisma 2 Case",
        "emoji": "🎂",
        "price": 2.0,
        "items": [
            {"name": "AUG | Tom Cat", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "AWP | Capillary", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "CZ75-Auto | Distressed", "rarity": "Blue", "condition": "Factory New"},
            {"name": "Desert Eagle | Blue Ply", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "MP5-SD | Desert Strike", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "Negev | Prototype", "rarity": "Blue", "condition": "Minimal Wear"},
            {"name": "R8 Revolver | Bone Forged", "rarity": "Blue", "condition": "Factory New"},
            {"name": "P2000 | Acid Etched", "rarity": "Purple", "condition": "Field-Tested"},
            {"name": "★ Navaja Knife", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Navaja Knife | Marble Fade", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Navaja Knife | Tiger Tooth", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"}
        ]
    },
    "fracture_case": {
        "name": "Fracture Case",
        "emoji": "💎",
        "price": 2.0,
        "items": [
            {"name": "Negev | Ultralight", "rarity": "Blue", "condition": "Minimal Wear"},
            {"name": "P2000 | Gnarled", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "SG 553 | Ol' Rusty", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "SSG 08 | Mainframe 001", "rarity": "Blue", "condition": "Factory New"},
            {"name": "P250 | Cassette", "rarity": "Blue", "condition": "Minimal Wear"},
            {"name": "P90 | Freight", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "PP-Bizon | Runic", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "MAG-7 | Monster Call", "rarity": "Purple", "condition": "Well-Worn"},
            {"name": "★ Nomad Knife", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Nomad Knife | Fade", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Nomad Knife | Crimson Web", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"}
        ]
    },
    "operation_broken_fang_case": {
        "name": "Operation Broken Fang Case",
        "emoji": "⚡",
        "price": 3.5,
        "items": [
            {"name": "CZ75-Auto | Vendetta", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "P90 | Cocoa Rampage", "rarity": "Blue", "condition": "Minimal Wear"},
            {"name": "G3SG1 | Digital Mesh", "rarity": "Blue", "condition": "Minimal Wear"},
            {"name": "Galil AR | Vandal", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "P250 | Contaminant", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "M249 | Deep Relief", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "MP5-SD | Condition Zero", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "AWP | Exoskeleton", "rarity": "Purple", "condition": "Factory New"},
            {"name": "★ Broken Fang Gloves | Yellow-banded", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Broken Fang Gloves | Unhinged", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Broken Fang Gloves | Needle Point", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"}
        ]
    },
    "snakebite_case": {
        "name": "Snakebite Case",
        "emoji": "🌊",
        "price": 2.5,
        "items": [
            {"name": "SG 553 | Heavy Metal", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "Glock-18 | Clear Polymer", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "M249 | O.S.I.P.R.", "rarity": "Blue", "condition": "Factory New"},
            {"name": "CZ75-Auto | Circaetus", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "UMP-45 | Oscillator", "rarity": "Blue", "condition": "Factory New"},
            {"name": "R8 Revolver | Junk Yard", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "Nova | Windblown", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "P250 | Cyber Shell", "rarity": "Purple", "condition": "Well-Worn"},
            {"name": "★ Broken Fang Gloves | Yellow-banded", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Broken Fang Gloves | Unhinged", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Broken Fang Gloves | Needle Point", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"}
        ]
    },
    "operation_riptide_case": {
        "name": "Operation Riptide Case",
        "emoji": "🌪️",
        "price": 3.0,
        "items": [
            {"name": "AUG | Plague", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "Dual Berettas | Tread", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "G3SG1 | Keeping Tabs", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "MP7 | Guerrilla", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "PP-Bizon | Lumen", "rarity": "Blue", "condition": "Factory New"},
            {"name": "USP-S | Black Lotus", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "XM1014 | Watchdog", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "MAG-7 | BI83 Spectrum", "rarity": "Purple", "condition": "Well-Worn"},
            {"name": "★ Bowie Knife | Gamma Doppler", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bowie Knife | Gamma Doppler", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bowie Knife | Gamma Doppler", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"}
        ]
    },
    "dreams_and_nightmares_case": {
        "name": "Dreams & Nightmares Case",
        "emoji": "🎇",
        "price": 2.5,
        "items": [
            {"name": "Five-SeveN | Scrawl", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "MAC-10 | Ensnared", "rarity": "Blue", "condition": "Minimal Wear"},
            {"name": "MAG-7 | Foresight", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "MP5-SD | Necro Jr.", "rarity": "Blue", "condition": "Factory New"},
            {"name": "P2000 | Lifted Spirits", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "SCAR-20 | Poultrygeist", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "Sawed-Off | Spirit Board", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "PP-Bizon | Space Cat", "rarity": "Purple", "condition": "Factory New"},
            {"name": "★ Bowie Knife | Gamma Doppler", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bowie Knife | Gamma Doppler", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Bowie Knife | Gamma Doppler", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"}
        ]
    },
    "recoil_case": {
        "name": "Recoil Case",
        "emoji": "📦",
        "price": 2.0,
        "items": [
            {"name": "FAMAS | Meow 36", "rarity": "Blue", "condition": "Factory New"},
            {"name": "Galil AR | Destroyer", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "M4A4 | Poly Mag", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "MAC-10 | Monkeyflage", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "Negev | Drop Me", "rarity": "Blue", "condition": "Minimal Wear"},
            {"name": "UMP-45 | Roadblock", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "Glock-18 | Winterized", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "R8 Revolver | Crazy 8", "rarity": "Purple", "condition": "Well-Worn"},
            {"name": "★ Broken Fang Gloves | Yellow-banded", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Broken Fang Gloves | Unhinged", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Broken Fang Gloves | Needle Point", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"}
        ]
    },
    "revolution_case": {
        "name": "Revolution Case",
        "emoji": "🎯",
        "price": 2.5,
        "items": [
            {"name": "MAG-7 | Insomnia", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "MP9 | Featherweight", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "SCAR-20 | Fragments", "rarity": "Blue", "condition": "Factory New"},
            {"name": "P250 | Re.built", "rarity": "Blue", "condition": "Minimal Wear"},
            {"name": "MP5-SD | Liquidation", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "SG 553 | Cyberforce", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "Tec-9 | Rebel", "rarity": "Blue", "condition": "Factory New"},
            {"name": "M4A1-S | Emphorosaur-S", "rarity": "Purple", "condition": "Factory New"},
            {"name": "★ Driver Gloves | Imperial Plaid", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Driver Gloves | King Snake", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Driver Gloves | Racing Green", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"}
        ]
    },
    "kilowatt_case": {
        "name": "Kilowatt Case",
        "emoji": "⚡",
        "price": 3.5,
        "items": [
            {"name": "Dual Berettas | Hideout", "rarity": "Blue", "condition": "Minimal Wear"},
            {"name": "MAC-10 | Light Box", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "Nova | Dark Sigil", "rarity": "Blue", "condition": "Factory New"},
            {"name": "SSG 08 | Dezastre", "rarity": "Blue", "condition": "Minimal Wear"},
            {"name": "Tec-9 | Slag", "rarity": "Blue", "condition": "Minimal Wear"},
            {"name": "UMP-45 | Motorized", "rarity": "Blue", "condition": "Factory New"},
            {"name": "XM1014 | Irezumi", "rarity": "Blue", "condition": "Factory New"},
            {"name": "Glock-18 | Block-18", "rarity": "Purple", "condition": "Minimal Wear"},
            {"name": "★ Kukri Knife", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Kukri Knife | Fade", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Kukri Knife | Slaughter", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"}
        ]
    },
    "gallery_case": {
        "name": "Gallery Case",
        "emoji": "🔥",
        "price": 3.0,
        "items": [
            {"name": "USP-S | 27", "rarity": "Blue", "condition": "Minimal Wear"},
            {"name": "Desert Eagle | Calligraffiti", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "MP5-SD | Statics", "rarity": "Blue", "condition": "Factory New"},
            {"name": "AUG | Luxe Trim", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "M249 | Hypnosis", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "R8 Revolver | Tango", "rarity": "Blue", "condition": "Factory New"},
            {"name": "SCAR-20 | Trail Blazer", "rarity": "Blue", "condition": "Factory New"},
            {"name": "M4A4 | Turbine", "rarity": "Purple", "condition": "Factory New"},
            {"name": "★ Kukri Knife", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Kukri Knife | Fade", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Kukri Knife | Slaughter", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"}
        ]
    },
    "fever_case": {
        "name": "Fever Case",
        "emoji": "💎",
        "price": 4.0,
        "items": [
            {"name": "M4A4 | Choppa", "rarity": "Blue", "condition": "Well-Worn"},
            {"name": "MAG-7 | Resupply", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "SSG 08 | Memorial", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "P2000 | Sure Grip", "rarity": "Blue", "condition": "Battle-Scarred"},
            {"name": "USP-S | PC-GRN", "rarity": "Blue", "condition": "Field-Tested"},
            {"name": "MP9 | Nexus", "rarity": "Blue", "condition": "Minimal Wear"},
            {"name": "XM1014 | Mockingbird", "rarity": "Blue", "condition": "Factory New"},
            {"name": "Desert Eagle | Serpent Strike", "rarity": "Purple", "condition": "Well-Worn"},
            {"name": "★ Survival Knife", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Survival Knife | Marble Fade", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"},
            {"name": "★ Survival Knife | Tiger Tooth", "rarity": "Gold", "tier": "Legendary", "condition": "Factory New"}
        ]
    },
}

# ============================================
# STICKER CAPSULES DATA
# ============================================

STICKER_CAPSULES = {
    "recoil": {
        "name": "Recoil Sticker Capsule", "emoji": CAPSULE_EMOJIS["recoil"], "price": 0.50,
        "stickers": [
            {"name": "CS2 Logo", "rarity": "⭐"}, {"name": "AWP Sniper", "rarity": "✨"},
            {"name": "Headshot", "rarity": "💫"}, {"name": "Clutch King", "rarity": "🔥"}
        ]
    },
    "dreams": {
        "name": "Dreams Sticker Capsule", "emoji": CAPSULE_EMOJIS["dreams"], "price": 1.00,
        "stickers": [
            {"name": "Phoenix Rising", "rarity": "⭐"}, {"name": "Dragon Lore", "rarity": "✨"},
            {"name": "Royal Crown", "rarity": "👑 Common"}, {"name": "Knight's Oath", "rarity": "👑 Rare"}
        ]
    },
    "cs20": {
        "name": "CS20 Sticker Capsule", "emoji": CAPSULE_EMOJIS["cs20"], "price": 1.00,
        "stickers": [
            {"name": "Counter-Terrorist Elite", "rarity": "⭐"}, {"name": "Terrorist Elite", "rarity": "✨"},
            {"name": "20 Years", "rarity": "💫"}, {"name": "Legends", "rarity": "👑 Epic"}
        ]
    },
    "championship": {
        "name": "Championship Sticker Capsule", "emoji": CAPSULE_EMOJIS["championship"], "price": 2.00,
        "stickers": [
            {"name": "Victory", "rarity": "✨"}, {"name": "Champion", "rarity": "💫"},
            {"name": "Golden Trophy", "rarity": "👑 Epic"}, {"name": "Hall of Fame", "rarity": "👑 Legendary"}
        ]
    },
    "legends": {
        "name": "Legends Sticker Capsule", "emoji": CAPSULE_EMOJIS["legends"], "price": 3.00,
        "stickers": [
            {"name": "s1mple", "rarity": "🔥"}, {"name": "ZyWoo", "rarity": "🔥"},
            {"name": "NiKo", "rarity": "👑 Rare"}, {"name": "KennyS", "rarity": "👑 Epic"}
        ]
    }
}

# ============================================
# CALCULATION FUNCTIONS
# ============================================

def calculate_item_value(rarity, condition=None, tier=None, is_stattrak=False):
    if rarity == "Gold" and tier:
        base_value = GOLD_VALUES.get(tier, 150)
    elif rarity in WEAPON_BASE_VALUES:
        base_value = WEAPON_BASE_VALUES[rarity]
    elif rarity in STICKER_VALUES:
        base_value = STICKER_VALUES[rarity]
    else:
        base_value = 0.25

    multiplier = CONDITION_MULTIPLIERS.get(condition, 1.0)
    value = base_value * multiplier

    if is_stattrak:
        value *= 2

    return round(value, 2)

def get_random_item(case_id):
    case = CASES.get(case_id)
    if not case or not case.get('items'):
        logger.error(f"Case {case_id} not found or has no items")
        return None

    rand = secure_random() * 100
    cumulative = 0

    for rarity, chance in DROP_RATES.items():
        cumulative += chance
        if rand <= cumulative:
            possible_items = [item for item in case['items'] if item['rarity'] == rarity]
            if possible_items:
                item = secure_choice(possible_items)
                is_stattrak = secure_random() < 0.1
                condition = item.get('condition', 'Field-Tested')
                tier = item.get('tier', None)
                
                float_value = generate_skin_float()
                condition_from_float = get_skin_condition(float_value)
                
                base_value = calculate_item_value(rarity, condition, tier, is_stattrak)
                float_multiplier = {
                    "Factory New": 2.0,
                    "Minimal Wear": 1.5,
                    "Field-Tested": 1.0,
                    "Well-Worn": 0.75,
                    "Battle-Scarred": 0.5
                }.get(condition_from_float, 1.0)
                
                value = round(base_value * float_multiplier, 2)

                if is_stattrak:
                    clean_name = item['name'].replace('StatTrak™ ', '').replace('StatTrak™', '')
                    name = f"StatTrak™ {clean_name}"
                else:
                    name = item['name']

                rarity_emoji = RARITY_EMOJIS.get(rarity, "")

                return {
                    'name': name,
                    'display_name': f"{rarity_emoji} {name}",
                    'rarity': rarity,
                    'rarity_emoji': rarity_emoji,
                    'tier': tier,
                    'condition': condition_from_float,
                    'float': float_value,
                    'price': value,
                    'is_stattrak': is_stattrak
                }

    if case['items']:
        fallback_item = case['items'][0]
        is_stattrak = secure_random() < 0.1
        condition = fallback_item.get('condition', 'Field-Tested')
        tier = fallback_item.get('tier', None)
        rarity = fallback_item['rarity']
        
        float_value = generate_skin_float()
        condition_from_float = get_skin_condition(float_value)
        
        base_value = calculate_item_value(rarity, condition, tier, is_stattrak)
        float_multiplier = {
            "Factory New": 2.0,
            "Minimal Wear": 1.5,
            "Field-Tested": 1.0,
            "Well-Worn": 0.75,
            "Battle-Scarred": 0.5
        }.get(condition_from_float, 1.0)
        value = round(base_value * float_multiplier, 2)

        if is_stattrak:
            clean_name = fallback_item['name'].replace('StatTrak™ ', '').replace('StatTrak™', '')
            name = f"StatTrak™ {clean_name}"
        else:
            name = fallback_item['name']

        rarity_emoji = RARITY_EMOJIS.get(rarity, "")

        return {
            'name': name,
            'display_name': f"{rarity_emoji} {name}",
            'rarity': rarity,
            'rarity_emoji': rarity_emoji,
            'tier': tier,
            'condition': condition_from_float,
            'float': float_value,
            'price': value,
            'is_stattrak': is_stattrak
        }

    return None

def get_random_sticker(capsule_id):
    capsule = STICKER_CAPSULES.get(capsule_id)
    if not capsule or not capsule.get('stickers'):
        return None

    sticker = secure_choice(capsule["stickers"])
    is_stattrak = secure_random() < 0.1
    value = calculate_item_value(sticker['rarity'], None, None, is_stattrak)

    if is_stattrak:
        clean_name = sticker['name'].replace('StatTrak™ ', '').replace('StatTrak™', '')
        name = f"StatTrak™ {clean_name}"
    else:
        name = sticker['name']

    return {
        'name': name,
        'rarity': sticker['rarity'],
        'price': value,
        'is_stattrak': is_stattrak
    }

# ============================================
# DATABASE FUNCTIONS
# ============================================

async def init_db():
    global db_pool
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        logger.error("❌ DATABASE_URL not set!")
        return False
    try:
        db_pool = await asyncpg.create_pool(db_url, min_size=5, max_size=20)
        logger.info("✅ Database pool ready!")
        
        # Ensure tables exist
        async with db_pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    balance DECIMAL(15,2) DEFAULT 1000,
                    credits INTEGER DEFAULT 0,
                    total_opens INTEGER DEFAULT 0,
                    total_premium_opens INTEGER DEFAULT 0,
                    total_golds INTEGER DEFAULT 0,
                    total_trades INTEGER DEFAULT 0,
                    daily_streak INTEGER DEFAULT 0,
                    last_daily TIMESTAMP,
                    last_hourly TIMESTAMP,
                    last_weekly TIMESTAMP,
                    total_hourly_claimed INTEGER DEFAULT 0,
                    total_weekly_claimed INTEGER DEFAULT 0,
                    xp INTEGER DEFAULT 0,
                    level INTEGER DEFAULT 1,
                    prestige INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS inventory (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                    item_name TEXT NOT NULL,
                    item_type TEXT DEFAULT 'weapon',
                    rarity TEXT,
                    price DECIMAL(15,2),
                    condition TEXT,
                    is_stattrak BOOLEAN DEFAULT FALSE,
                    status TEXT DEFAULT 'kept',
                    case_id TEXT,
                    float_value DECIMAL(10,4),
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS guild_settings (
                    guild_id BIGINT PRIMARY KEY,
                    name TEXT,
                    bot_channel_id BIGINT,
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS quests (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                    quest_type TEXT,
                    progress INTEGER DEFAULT 0,
                    required INTEGER,
                    reward INTEGER,
                    completed BOOLEAN DEFAULT FALSE,
                    claimed BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS giveaways (
                    id SERIAL PRIMARY KEY,
                    creator_id BIGINT REFERENCES users(user_id) ON DELETE SET NULL,
                    message_id BIGINT,
                    channel_id BIGINT,
                    prize TEXT,
                    prize_amount DECIMAL(10,2),
                    winner_count INTEGER DEFAULT 1,
                    end_time TIMESTAMP,
                    ends_at TIMESTAMP,
                    status TEXT DEFAULT 'active',
                    ended BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS giveaway_entries (
                    id SERIAL PRIMARY KEY,
                    giveaway_id INTEGER REFERENCES giveaways(id) ON DELETE CASCADE,
                    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                    created_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE (giveaway_id, user_id)
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS coinflip_games (
                    id SERIAL PRIMARY KEY,
                    creator_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                    opponent_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                    amount DECIMAL(15,2),
                    winner_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                    status TEXT DEFAULT 'waiting',
                    created_at TIMESTAMP DEFAULT NOW(),
                    completed_at TIMESTAMP
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS dice_games (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                    amount DECIMAL(15,2),
                    bet_type TEXT,
                    bet_number INTEGER,
                    roll_number INTEGER,
                    result TEXT,
                    multiplier DECIMAL(10,2),
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS mines_games (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                    bet_amount DECIMAL(15,2),
                    grid_size INTEGER DEFAULT 5,
                    mine_count INTEGER DEFAULT 3,
                    status TEXT DEFAULT 'active',
                    mine_positions INTEGER[],
                    revealed_tiles INTEGER[] DEFAULT '{}',
                    multiplier DECIMAL(10,2) DEFAULT 1.0,
                    exploded BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS slots_games (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                    bet_amount DECIMAL(15,2),
                    spin_result TEXT[],
                    multiplier DECIMAL(10,2),
                    win_amount DECIMAL(15,2),
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_achievements (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                    achievement_id TEXT,
                    unlocked_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_streaks (
                    user_id BIGINT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
                    current_streak INTEGER DEFAULT 0,
                    best_streak INTEGER DEFAULT 0,
                    golds_in_streak INTEGER DEFAULT 0,
                    total_session_opens INTEGER DEFAULT 0,
                    current_case_id TEXT,
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id BIGINT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
                    theme TEXT DEFAULT 'casino',
                    spin_speed TEXT DEFAULT 'normal',
                    sound_enabled BOOLEAN DEFAULT TRUE,
                    feed_enabled BOOLEAN DEFAULT TRUE,
                    confetti_mode TEXT DEFAULT 'always',
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS live_feed (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                    username TEXT,
                    item_name TEXT,
                    rarity TEXT,
                    rarity_emoji TEXT,
                    case_type TEXT,
                    float_value DECIMAL(10,4),
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS donations (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                    amount DECIMAL(15,2),
                    donor_name TEXT,
                    donor_email TEXT,
                    payment_provider TEXT DEFAULT 'stripe',
                    stripe_payment_id TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS ticket_purchases (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                    amount INTEGER,
                    cost_usd DECIMAL(10,2),
                    stripe_session_id TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS skin_upgrades (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                    item_id INTEGER,
                    input_rarity TEXT,
                    output_rarity TEXT,
                    success BOOLEAN,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
        
        asyncio.create_task(keep_db_alive())
        return True
    except Exception as e:
        logger.error(f"❌ Database error: {e}")
        return False

async def keep_db_alive():
    while True:
        await asyncio.sleep(300)
        try:
            async with db_pool.acquire() as conn:
                await conn.execute("SELECT 1")
            logger.debug("Database keep-alive ping successful")
        except Exception as e:
            logger.error(f"Database keep-alive failed: {e}")
            await init_db()

async def ensure_user_exists(user_id: int, username: str = None, conn=None):
    """CRITICAL FIX: Ensure user exists before any transaction"""
    try:
        if conn is None:
            async with db_pool.acquire() as conn:
                return await ensure_user_exists(user_id, username, conn)
        
        await conn.execute("""
            INSERT INTO users (user_id, username, balance, created_at, updated_at)
            VALUES ($1, $2, 1000, NOW(), NOW())
            ON CONFLICT (user_id) DO NOTHING
        """, user_id, username or f"User_{user_id}")
        return True
    except Exception as e:
        logger.error(f"ensure_user_exists error for {user_id}: {e}")
        return False

async def get_balance(user_id, conn=None):
    if conn is None:
        async with db_pool.acquire() as conn:
            return await get_balance(user_id, conn)
    
    await ensure_user_exists(user_id, conn=conn)
    user = await conn.fetchrow("SELECT balance FROM users WHERE user_id = $1", user_id)
    if not user:
        return 1000
    return user['balance']

async def create_daily_quests(user_id, conn=None):
    if conn is None:
        async with db_pool.acquire() as conn:
            return await create_daily_quests(user_id, conn)
    
    await ensure_user_exists(user_id, conn=conn)
    
    last_quest = await conn.fetchrow("""
        SELECT created_at FROM quests WHERE user_id = $1
        ORDER BY created_at DESC LIMIT 1
    """, user_id)

    if last_quest and last_quest['created_at'].date() == datetime.now().date():
        return

    await conn.execute("DELETE FROM quests WHERE user_id = $1", user_id)

    for quest_type, quest_info in QUEST_TYPES.items():
        required = quest_info["base_required"]
        reward = quest_info["base_reward"]
        user = await conn.fetchrow("SELECT total_opens FROM users WHERE user_id = $1", user_id)
        if user and user['total_opens'] > 100:
            required = int(required * 1.5)
            reward = int(reward * 1.2)
        await conn.execute("""
            INSERT INTO quests (user_id, quest_type, progress, required, reward, completed, claimed, created_at)
            VALUES ($1, $2, 0, $3, $4, false, false, NOW())
        """, user_id, quest_type, required, reward)

async def update_quest_progress(user_id, quest_type, increment=1, conn=None):
    if conn is None:
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                return await update_quest_progress(user_id, quest_type, increment, conn)

    await ensure_user_exists(user_id, conn=conn)

    try:
        # FOR UPDATE prevents a TOCTOU race where two concurrent callers both
        # read the same progress value and each increments by the same amount,
        # producing only one net increment instead of two.
        quest = await conn.fetchrow("""
            SELECT id, progress, required FROM quests
            WHERE user_id = $1 AND quest_type = $2 AND completed = false AND claimed = false
            FOR UPDATE
        """, user_id, quest_type)

        if quest:
            new_progress = quest['progress'] + increment
            if new_progress >= quest['required']:
                await conn.execute("""
                    UPDATE quests SET progress = $1, completed = true WHERE id = $2
                """, quest['required'], quest['id'])
                logger.info(f"Quest {quest_type} completed for user {user_id}")
                return True
            else:
                await conn.execute("""
                    UPDATE quests SET progress = $1 WHERE id = $2
                """, new_progress, quest['id'])
                return True
        return False
    except Exception as e:
        logger.error(f"Quest update error: {e}")
        return False

@bot.event
async def on_ready():
    global db_pool
    if not db_pool:
        await init_db()

    # ── Load admin/moderator IDs from env into shared module ──
    try:
        import shared as _shared
        admin_env = os.getenv('ADMIN_USER_IDS', '')
        mod_env   = os.getenv('MODERATOR_USER_IDS', '')
        if admin_env:
            _shared.ADMIN_USER_IDS.update(
                int(x.strip()) for x in admin_env.split(',') if x.strip()
            )
        if mod_env:
            _shared.MODERATOR_USER_IDS.update(
                int(x.strip()) for x in mod_env.split(',') if x.strip()
            )
        logger.info(f"👑 Admin IDs: {_shared.ADMIN_USER_IDS}")
    except Exception as e:
        logger.warning(f"Could not load admin IDs: {e}")

    logger.info(f'✅ {bot.user} is now online!')
    logger.info(f'🎮 Bot is ready on {len(bot.guilds)} servers')
    logger.info(f'📦 Total cases loaded: {len(CASES)}')
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=f"CS2 Cases | Join: {DISCORD_INVITE_URL}"))
    try:
        synced = await bot.tree.sync()
        logger.info(f"✅ Synced {len(synced)} slash commands")
    except Exception as e:
        logger.error(f"Error syncing commands: {e}")

    # Recover any giveaways that were running before a restart.
    try:
        now_utc = datetime.utcnow()
        async with db_pool.acquire() as conn:
            pending = await conn.fetch(
                "SELECT id, end_time FROM giveaways WHERE ended = false AND end_time > $1",
                now_utc
            )
            expired = await conn.fetch(
                "SELECT id FROM giveaways WHERE ended = false AND end_time <= $1",
                now_utc
            )
        for row in pending:
            delay = max(0.0, (row['end_time'] - now_utc).total_seconds())
            asyncio.create_task(_run_giveaway(row['id'], delay))
        for row in expired:
            asyncio.create_task(_run_giveaway(row['id'], 0))
        logger.info(f"🎉 Recovered {len(pending)} pending + {len(expired)} expired giveaways")
    except Exception as e:
        logger.error(f"Giveaway recovery failed: {e}")

# ============================================
# XP SYSTEM
# ============================================

async def add_xp(user_id: int, amount: int, conn=None):
    if conn is None:
        async with db_pool.acquire() as conn:
            return await add_xp(user_id, amount, conn)
    
    await ensure_user_exists(user_id, conn=conn)
    
    async with conn.transaction():
        user = await conn.fetchrow(
            "SELECT xp, level, prestige FROM users WHERE user_id = $1 FOR UPDATE",
            user_id
        )
        if not user:
            return
        
        new_xp = (user['xp'] or 0) + amount
        current_level = user['level'] or 1
        # Track prestige locally so each milestone in the same call sees the
        # running total (not the stale value from the initial SELECT).
        prestige = user['prestige'] or 0
        leveled_up = False

        xp_needed = current_level * 50 + 100

        while new_xp >= xp_needed:
            new_xp -= xp_needed
            current_level += 1
            xp_needed = current_level * 50 + 100
            leveled_up = True

            reward = current_level * 50
            await conn.execute(
                "UPDATE users SET balance = balance + $1 WHERE user_id = $2",
                reward, user_id
            )

            if current_level % 50 == 0:
                prestige += 1
                await conn.execute(
                    "UPDATE users SET prestige = $1 WHERE user_id = $2",
                    prestige, user_id
                )
                bonus = prestige * 1000
                await conn.execute(
                    "UPDATE users SET balance = balance + $1 WHERE user_id = $2",
                    bonus, user_id
                )
        
        await conn.execute(
            "UPDATE users SET xp = $1, level = $2 WHERE user_id = $3",
            new_xp, current_level, user_id
        )
        
        return {'level': current_level, 'xp': new_xp, 'leveled_up': leveled_up}

# ============================================
# PAGINATED INVENTORY VIEW
# ============================================

class InventoryView(discord.ui.View):
    def __init__(self, items, user, items_per_page=10):
        super().__init__(timeout=120)
        self.items = items
        self.user = user
        self.items_per_page = items_per_page
        self.current_page = 0
        self.total_pages = max(1, (len(items) + items_per_page - 1) // items_per_page)
        self.message = None

    def get_embed(self):
        start = self.current_page * self.items_per_page
        end = start + self.items_per_page
        page_items = self.items[start:end]

        total_value = sum(float(item['price']) for item in self.items)

        embed = discord.Embed(title=f"📦 {self.user.display_name}'s Inventory", color=discord.Color.gold())

        weapon_list = ""
        sticker_list = ""

        for item in page_items:
            stattrak = "ⓢ™️ " if item['is_stattrak'] else ""
            rarity_emoji = RARITY_EMOJIS.get(item['rarity'], "")
            float_display = f" | Float: {item.get('float_value', 0.0000):.4f}" if item.get('float_value') is not None else ""
            item_text = f"**ID:{item['id']}** {stattrak}{rarity_emoji} {item['item_name']} - ${float(item['price']):,.2f}{float_display}\n"
            if item['item_type'] == 'weapon':
                if len(weapon_list) + len(item_text) < 1024:
                    weapon_list += item_text
            else:
                if len(sticker_list) + len(item_text) < 1024:
                    sticker_list += item_text

        if weapon_list:
            embed.add_field(name="🎮 Weapons", value=weapon_list, inline=False)
        if sticker_list:
            embed.add_field(name="⭐ Stickers", value=sticker_list, inline=False)

        embed.add_field(name="💰 Total Inventory Value", value=f"${total_value:,.2f}", inline=False)
        embed.set_footer(text=f"Page {self.current_page + 1}/{self.total_pages} | 💖 Support: {KO_FI_URL} | 🌐 Dashboard: {DASHBOARD_URL}")

        return embed

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except:
                pass

    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.secondary)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ This inventory belongs to someone else!", ephemeral=True)
            return

        self.current_page = (self.current_page - 1) % self.total_pages
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ This inventory belongs to someone else!", ephemeral=True)
            return

        self.current_page = (self.current_page + 1) % self.total_pages
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

# ============================================
# ECONOMY COMMANDS
# ============================================

@bot.tree.command(name="balance", description="Check your balance")
async def balance(interaction: discord.Interaction):
    if not await is_bot_channel(interaction):
        return
    await interaction.response.defer()
    async with db_pool.acquire() as conn:
        await ensure_user_exists(interaction.user.id, interaction.user.display_name, conn)
        user = await conn.fetchrow("SELECT balance FROM users WHERE user_id = $1", interaction.user.id)
        if not user:
            await conn.execute("INSERT INTO users (user_id, balance) VALUES ($1, $2)", interaction.user.id, 1000)
            bal = 1000
        else:
            bal = user['balance']
    embed = discord.Embed(title="💰 Balance", color=discord.Color.green())
    embed.add_field(name=interaction.user.display_name, value=f"${bal:,.2f}", inline=False)
    embed.set_footer(text=f"💖 Support us: {KO_FI_URL} | 🌐 Dashboard: {DASHBOARD_URL}")
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="daily", description="Claim your daily reward")
async def daily(interaction: discord.Interaction):
    if not await is_bot_channel(interaction):
        return
    await interaction.response.defer()
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            await ensure_user_exists(interaction.user.id, interaction.user.display_name, conn)

            # SELECT FOR UPDATE locks the row so concurrent daily claims queue up
            # rather than both passing the date check simultaneously.
            user = await conn.fetchrow(
                "SELECT daily_streak, last_daily, balance FROM users WHERE user_id = $1 FOR UPDATE",
                interaction.user.id
            )
            if not user:
                await conn.execute("INSERT INTO users (user_id, balance) VALUES ($1, $2)", interaction.user.id, 1000)
                await create_daily_quests(interaction.user.id, conn)
                user = await conn.fetchrow(
                    "SELECT daily_streak, last_daily, balance FROM users WHERE user_id = $1 FOR UPDATE",
                    interaction.user.id
                )

            now = datetime.now()
            last_daily = user['last_daily']
            streak = user['daily_streak'] or 0

            if last_daily and last_daily.date() == now.date():
                embed = discord.Embed(title="⏰ Already Claimed", description="You've already claimed today's daily reward!", color=discord.Color.red())
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            if last_daily and last_daily.date() == (now - timedelta(days=1)).date():
                streak += 1
            else:
                streak = 1

            reward = 500 + (streak * 100)
            jackpot_hit = secure_randint(1, 1000000) == 1

            if jackpot_hit:
                reward += 50000

            streak_bonus = {10: 25, 25: 75, 50: 250, 100: 1000}.get(streak, 0)
            reward += streak_bonus

            await conn.execute("UPDATE users SET balance = balance + $1, daily_streak = $2, last_daily = $3 WHERE user_id = $4", reward, streak, now, interaction.user.id)

            updated_user = await conn.fetchrow("SELECT balance FROM users WHERE user_id = $1", interaction.user.id)
            new_balance = updated_user['balance'] if updated_user else reward

        # Send jackpot notification outside the transaction so a Discord error
        # cannot roll back the already-committed balance update.
        if jackpot_hit:
            embed2 = discord.Embed(title="🎰🎰🎰 JACKPOT! 🎰🎰🎰", description=f"You won an additional **$50,000**!", color=discord.Color.gold())
            await interaction.followup.send(embed2)

        embed = discord.Embed(title="🎁 Daily Reward Claimed!", color=discord.Color.green())
        embed.add_field(name="Reward", value=f"${reward:,.2f}", inline=True)
        embed.add_field(name="Streak", value=f"{streak} days", inline=True)
        embed.add_field(name="New Balance", value=f"${new_balance:,.2f}", inline=True)

        if streak_bonus:
            embed.add_field(name="🏆 Streak Bonus", value=f"${streak_bonus} added!", inline=True)

        await update_quest_progress(interaction.user.id, "daily_streak", 1)
        embed.set_footer(text=f"💖 Support us: {KO_FI_URL} | 🌐 Dashboard: {DASHBOARD_URL}")
        await interaction.followup.send(embed=embed)

@bot.tree.command(name="transfer", description="Transfer money to another user")
async def transfer(interaction: discord.Interaction, user: discord.User, amount: float):
    if not await is_bot_channel(interaction):
        return
    await interaction.response.defer()
    if amount <= 0:
        await interaction.followup.send("Amount must be positive!", ephemeral=True)
        return
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            await ensure_user_exists(interaction.user.id, interaction.user.display_name, conn)
            await ensure_user_exists(user.id, user.display_name, conn)

            # Atomic deduct: WHERE balance >= $1 prevents negative balance under concurrency
            updated = await conn.fetchrow(
                "UPDATE users SET balance = balance - $1 WHERE user_id = $2 AND balance >= $1 RETURNING balance",
                amount, interaction.user.id
            )
            if not updated:
                await interaction.followup.send("Insufficient balance!", ephemeral=True)
                return
            await conn.execute("UPDATE users SET balance = balance + $1 WHERE user_id = $2", amount, user.id)
            new_balance = float(updated['balance'])
        embed = discord.Embed(title="💸 Transfer Complete", color=discord.Color.green())
        embed.add_field(name="Sender", value=interaction.user.display_name, inline=True)
        embed.add_field(name="Receiver", value=user.display_name, inline=True)
        embed.add_field(name="Amount", value=f"${amount:,.2f}", inline=True)
        embed.add_field(name="Your New Balance", value=f"${new_balance:,.2f}", inline=True)
        embed.set_footer(text=f"💖 Support us: {KO_FI_URL} | 🌐 Dashboard: {DASHBOARD_URL}")
        await interaction.followup.send(embed=embed)

# ============================================
# CASE COMMANDS
# ============================================

@bot.tree.command(name="cases", description="View available cases")
async def list_cases(interaction: discord.Interaction):
    if not await is_bot_channel(interaction):
        return

    await interaction.response.defer()

    case_items = list(CASES.items())
    chunks = [case_items[i:i+20] for i in range(0, len(case_items), 20)]
    total_pages = len(chunks)
    
    class CaseView(discord.ui.View):
        def __init__(self, chunks_data):
            super().__init__(timeout=120)
            self.chunks = chunks_data
            self.current_page = 0
            self.total_pages = len(chunks_data)
            self.message = None
        
        def get_embed(self):
            embed = discord.Embed(
                title=f"📦 Available Cases ({len(CASES)}) - Page {self.current_page + 1}/{self.total_pages}",
                color=discord.Color.blue()
            )
            for case_id, case_data in self.chunks[self.current_page]:
                embed.add_field(
                    name=f"{case_data['emoji']} {case_data['name']}",
                    value=f"Price: ${case_data['price']:.2f}\nUse: `/open {case_id}`",
                    inline=True
                )
            embed.set_footer(text=f"💖 Support us: {KO_FI_URL} | 🌐 Dashboard: {DASHBOARD_URL}")
            return embed
        
        @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.secondary)
        async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            self.current_page = (self.current_page - 1) % self.total_pages
            await interaction.response.edit_message(embed=self.get_embed(), view=self)
        
        @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
        async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            self.current_page = (self.current_page + 1) % self.total_pages
            await interaction.response.edit_message(embed=self.get_embed(), view=self)
        
        async def on_timeout(self):
            for item in self.children:
                item.disabled = True
            if self.message:
                try:
                    await self.message.edit(view=self)
                except:
                    pass

    view = CaseView(chunks)
    response = await interaction.followup.send(embed=view.get_embed(), view=view)
    view.message = response

@bot.tree.command(name="open", description="Open a case")
async def open_case(interaction: discord.Interaction, case: str):
    if not await is_bot_channel(interaction):
        return

    await interaction.response.defer()

    case_id = case.lower()
    if case_id not in CASES:
        await interaction.followup.send("❌ Invalid case! Use `/cases` to see available cases.", ephemeral=True)
        return

    case_data = CASES[case_id]

    try:
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                await ensure_user_exists(interaction.user.id, interaction.user.display_name, conn)
                
                # Atomic deduct: WHERE balance >= $1 prevents negative balance under concurrency.
                deducted = await conn.fetchval(
                    "UPDATE users SET balance = balance - $1, total_opens = total_opens + 1 WHERE user_id = $2 AND balance >= $1 RETURNING user_id",
                    case_data['price'], interaction.user.id
                )
                if not deducted:
                    embed = discord.Embed(title="❌ Insufficient Balance", description=f"You need ${case_data['price']:.2f} to open this case!", color=discord.Color.red())
                    embed.set_footer(text=f"💖 Support: {KO_FI_URL} | 🌐 Dashboard: {DASHBOARD_URL}")
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return

                item = get_random_item(case_id)

                if item is None:
                    await interaction.followup.send("❌ Error opening case. Please try again.", ephemeral=True)
                    return

                price_value = float(item['price'])

                await conn.execute("""INSERT INTO inventory 
                    (user_id, item_name, item_type, rarity, price, condition, is_stattrak, float_value) 
                    VALUES ($1, $2, 'weapon', $3, $4, $5, $6, $7)""",
                    interaction.user.id, item['name'], item['rarity'], price_value, 
                    item.get('condition', 'Field-Tested'), item['is_stattrak'], 
                    item.get('float', 0.0000))

                if item['rarity'] == "Gold":
                    await conn.execute("UPDATE users SET total_golds = total_golds + 1 WHERE user_id = $1", interaction.user.id)
                    await update_quest_progress(interaction.user.id, "get_golds", 1, conn)

                await update_quest_progress(interaction.user.id, "open_cases", 1, conn)
                await update_quest_progress(interaction.user.id, "earn_money", int(case_data['price']), conn)

                new_balance = await get_balance(interaction.user.id, conn)

                await add_xp(interaction.user.id, 25, conn)

                color_map = {"Gold": 0xffd700, "Red": 0xff4444, "Pink": 0xff69b4, "Purple": 0xaa00ff, "Blue": 0x0066cc}
                embed = discord.Embed(title=f"🔑 Opening {case_data['emoji']} {case_data['name']}...", color=color_map.get(item['rarity'], 0x808080))
                embed.add_field(name="✨ You got:", value=f"**{item['display_name']}**", inline=False)
                embed.add_field(name="Rarity", value=item['rarity'], inline=True)
                embed.add_field(name="Condition", value=item.get('condition', 'N/A'), inline=True)
                embed.add_field(name="🔢 Float", value=f"{item.get('float', 0.0000):.4f}", inline=True)
                embed.add_field(name="Value", value=f"${item['price']:,.2f}", inline=True)
                if item['is_stattrak']:
                    embed.add_field(name="🔥 StatTrak™", value="Rare StatTrak™ variant!", inline=False)
                embed.add_field(name="💰 Cost", value=f"${case_data['price']:.2f}", inline=True)
                embed.add_field(name="💰 New Balance", value=f"${new_balance:,.2f}", inline=True)
                embed.set_footer(text=f"💖 Support us: {KO_FI_URL} | 🌐 Dashboard: {DASHBOARD_URL}")

                await interaction.followup.send(embed=embed)
    except Exception as e:
        logger.error(f"Open case error: {e}")
        await interaction.followup.send(f"❌ Error opening case: {str(e)[:100]}", ephemeral=True)

# ============================================
# BULK OPEN COMMAND
# ============================================

@bot.tree.command(name="bulkopen", description="Open multiple cases at once with discount (5,10,15,20,25)")
async def bulk_open(interaction: discord.Interaction, case: str, quantity: int):
    if not await is_bot_channel(interaction):
        return

    valid_quantities = [5, 10, 15, 20, 25]
    if quantity not in valid_quantities:
        await interaction.response.send_message(f"❌ Invalid quantity! Choose from: {', '.join(str(q) for q in valid_quantities)}", ephemeral=True)
        return

    await interaction.response.defer()

    case_id = case.lower()
    if case_id not in CASES:
        await interaction.followup.send("❌ Invalid case! Use `/cases` to see available cases.", ephemeral=True)
        return

    case_data = CASES[case_id]

    discount_percent = {5: 5, 10: 10, 15: 15, 20: 20, 25: 25}[quantity]
    discount_multiplier = {5: 0.95, 10: 0.90, 15: 0.85, 20: 0.80, 25: 0.75}[quantity]
    total_cost = round(case_data['price'] * quantity * discount_multiplier, 2)

    try:
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                await ensure_user_exists(interaction.user.id, interaction.user.display_name, conn)

                # Atomic deduct + opens increment; WHERE balance >= $1 prevents
                # negative balance under concurrent bulkopen requests.
                deducted = await conn.fetchval(
                    "UPDATE users SET balance = balance - $1, total_opens = total_opens + $2 WHERE user_id = $3 AND balance >= $1 RETURNING balance",
                    total_cost, quantity, interaction.user.id
                )
                if deducted is None:
                    embed = discord.Embed(title="❌ Insufficient Balance", description=f"You need ${total_cost:.2f} to open {quantity} {case_data['name']}s!", color=discord.Color.red())
                    embed.set_footer(text=f"💖 Support: {KO_FI_URL} | 🌐 Dashboard: {DASHBOARD_URL}")
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return

                old_balance = float(deducted) + total_cost
                items = []
                for _ in range(quantity):
                    item = get_random_item(case_id)
                    if item:
                        price_value = float(item['price'])
                        result = await conn.fetchrow("""INSERT INTO inventory 
                            (user_id, item_name, item_type, rarity, price, condition, is_stattrak, status, float_value) 
                            VALUES ($1, $2, 'weapon', $3, $4, $5, $6, 'kept', $7) RETURNING id""",
                            interaction.user.id, item['name'], item['rarity'], price_value, 
                            item.get('condition', 'Field-Tested'), item['is_stattrak'],
                            item.get('float', 0.0000))
                        if result:
                            item['id'] = result['id']
                        items.append(item)

                        if item['rarity'] == "Gold":
                            await conn.execute("UPDATE users SET total_golds = total_golds + 1 WHERE user_id = $1", interaction.user.id)
                            await update_quest_progress(interaction.user.id, "get_golds", 1, conn)

                if not items:
                    await interaction.followup.send("❌ Error: No items were generated. Please try again.", ephemeral=True)
                    return

                await update_quest_progress(interaction.user.id, "open_cases", quantity, conn)
                await update_quest_progress(interaction.user.id, "earn_money", int(total_cost), conn)

                new_balance = await get_balance(interaction.user.id, conn)
                await add_xp(interaction.user.id, quantity * 10, conn)

                item_summary = ""
                for i, item in enumerate(items[:10], 1):
                    float_display = f" (Float: {item.get('float', 0.0000):.4f})" if item.get('float') is not None else ""
                    item_summary += f"{i}. {item['display_name']} - ${item['price']:.2f}{float_display}\n"
                if len(items) > 10:
                    item_summary += f"... and {len(items) - 10} more items"

                embed = discord.Embed(title=f"🔑 Bulk Opened {quantity} {case_data['name']}s!", color=discord.Color.purple())
                embed.add_field(name="📦 Items Obtained", value=item_summary[:1024], inline=False)
                embed.add_field(name="💰 Total Cost", value=f"${total_cost:.2f} ({discount_percent}% discount!)", inline=True)
                embed.add_field(name="💰 Previous Balance", value=f"${old_balance:.2f}", inline=True)
                embed.add_field(name="💰 New Balance", value=f"${new_balance:.2f}", inline=True)
                embed.set_footer(text=f"💖 Support us: {KO_FI_URL} | 🌐 Dashboard: {DASHBOARD_URL}")

                await interaction.followup.send(embed=embed)
    except Exception as e:
        logger.error(f"Bulk open error: {e}")
        await interaction.followup.send(f"❌ Error opening cases: {str(e)[:100]}", ephemeral=True)

# ============================================
# STICKER CAPSULE COMMANDS
# ============================================

@bot.tree.command(name="capsules", description="View available sticker capsules")
async def list_capsules(interaction: discord.Interaction):
    if not await is_bot_channel(interaction):
        return

    await interaction.response.defer()

    embed = discord.Embed(title="📦 Available Sticker Capsules (5)", color=discord.Color.purple())
    for capsule_id, capsule_data in STICKER_CAPSULES.items():
        embed.add_field(name=f"{capsule_data['emoji']} {capsule_data['name']}", value=f"Price: ${capsule_data['price']:.2f}\nUse: `/sticker {capsule_id}`", inline=True)
    embed.set_footer(text=f"💖 Support us: {KO_FI_URL} | 🌐 Dashboard: {DASHBOARD_URL}")
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="sticker", description="Open a sticker capsule")
async def open_sticker(interaction: discord.Interaction, capsule: str):
    if not await is_bot_channel(interaction):
        return

    await interaction.response.defer()

    capsule_id = capsule.lower()
    if capsule_id not in STICKER_CAPSULES:
        await interaction.followup.send("❌ Invalid capsule! Use `/capsules` to see available capsules.", ephemeral=True)
        return

    capsule_data = STICKER_CAPSULES[capsule_id]

    try:
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                await ensure_user_exists(interaction.user.id, interaction.user.display_name, conn)

                # Atomic deduct: WHERE balance >= $1 prevents negative balance under concurrency.
                deducted = await conn.fetchval(
                    "UPDATE users SET balance = balance - $1 WHERE user_id = $2 AND balance >= $1 RETURNING balance",
                    capsule_data['price'], interaction.user.id
                )
                if deducted is None:
                    embed = discord.Embed(title="❌ Insufficient Balance", description=f"You need ${capsule_data['price']:.2f} to open this capsule!", color=discord.Color.red())
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return

                sticker = get_random_sticker(capsule_id)

                if not sticker:
                    await interaction.followup.send("❌ Error opening sticker capsule. Please try again.", ephemeral=True)
                    return

                await conn.execute("INSERT INTO inventory (user_id, item_name, item_type, rarity, price, is_stattrak) VALUES ($1, $2, 'sticker', $3, $4, $5)",
                                  interaction.user.id, sticker['name'], sticker['rarity'], sticker['price'], sticker['is_stattrak'])

                new_balance = await get_balance(interaction.user.id, conn)

                color_map = {"👑 Legendary": 0xffd700, "👑 Epic": 0xaa00ff, "👑 Rare": 0x0066cc, "👑 Common": 0x00aa00, "🔥": 0xff4444, "💫": 0xff69b4, "✨": 0xaa00ff, "⭐": 0x0066cc}

                embed = discord.Embed(title=f"⭐ Opening {capsule_data['emoji']} {capsule_data['name']}...", color=color_map.get(sticker['rarity'], 0x808080))
                embed.add_field(name="✨ You got:", value=f"**{sticker['name']}**", inline=False)
                embed.add_field(name="Rarity", value=sticker['rarity'], inline=True)
                embed.add_field(name="Value", value=f"${sticker['price']:.2f}", inline=True)
                if sticker['is_stattrak']:
                    embed.add_field(name="🔥 StatTrak™", value="Rare StatTrak™ variant!", inline=False)
                embed.add_field(name="💰 Cost", value=f"${capsule_data['price']:.2f}", inline=True)
                embed.add_field(name="💰 New Balance", value=f"${new_balance:,.2f}", inline=True)
                embed.set_footer(text=f"💖 Support us: {KO_FI_URL} | 🌐 Dashboard: {DASHBOARD_URL}")

                await interaction.followup.send(embed=embed)
    except Exception as e:
        logger.error(f"Open sticker error: {e}")
        await interaction.followup.send(f"❌ Error opening sticker: {str(e)[:100]}", ephemeral=True)

# ============================================
# INVENTORY COMMANDS
# ============================================

@bot.tree.command(name="inventory", description="View your inventory")
async def view_inventory(interaction: discord.Interaction, filter_type: str = None, search: str = None):
    if not await is_bot_channel(interaction):
        return

    await interaction.response.defer()

    async with db_pool.acquire() as conn:
        await ensure_user_exists(interaction.user.id, interaction.user.display_name, conn)
        
        query = "SELECT id, item_name, item_type, rarity, price, is_stattrak, float_value, condition FROM inventory WHERE user_id = $1 AND status = 'kept'"
        params = [interaction.user.id]

        if filter_type:
            filter_lower = filter_type.lower()
            if filter_lower == 'weapon':
                query += " AND item_type = 'weapon'"
            elif filter_lower == 'sticker':
                query += " AND item_type = 'sticker'"

        if search:
            query += " AND LOWER(item_name) LIKE $" + str(len(params) + 1)
            params.append(f"%{search.lower()}%")

        query += " ORDER BY created_at DESC"
        items = await conn.fetch(query, *params)

        if not items:
            embed = discord.Embed(title="📦 Inventory", description="Your inventory is empty! Open some cases with `/open` or `/sticker`", color=discord.Color.blue())
            embed.set_footer(text=f"💖 Support us: {KO_FI_URL} | 🌐 Dashboard: {DASHBOARD_URL}")
            await interaction.followup.send(embed=embed)
            return

        view = InventoryView(items, interaction.user)
        response = await interaction.followup.send(embed=view.get_embed(), view=view)
        view.message = response

# ============================================
# SELL COMMAND
# ============================================

@bot.tree.command(name="sell", description="Sell an item from your inventory")
async def sell_item(interaction: discord.Interaction, item_id: int):
    if not await is_bot_channel(interaction):
        return

    await interaction.response.defer()

    try:
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                await ensure_user_exists(interaction.user.id, interaction.user.display_name, conn)
                
                item = await conn.fetchrow(
                    "UPDATE inventory SET status='sold' WHERE id=$1 AND user_id=$2 AND status='kept' RETURNING *",
                    item_id, interaction.user.id
                )

                if not item:
                    await interaction.followup.send(f"❌ Item ID {item_id} not found in your inventory! Use `/inventory` to see your items.", ephemeral=True)
                    return

                price_value = float(item['price']) if isinstance(item['price'], Decimal) else item['price']
                sell_price = int(price_value * 0.7)

                old_balance = await get_balance(interaction.user.id, conn)

                await conn.execute("UPDATE users SET balance = balance + $1 WHERE user_id = $2", sell_price, interaction.user.id)

                await update_quest_progress(interaction.user.id, "sell_items", 1, conn)

                new_balance = await get_balance(interaction.user.id, conn)

                embed = discord.Embed(title="💰 Item Sold!", color=discord.Color.green())
                embed.add_field(name="Sold", value=item['item_name'], inline=False)
                embed.add_field(name="Received", value=f"${sell_price:,.2f}", inline=True)
                embed.add_field(name="Original Value", value=f"${price_value:,.2f}", inline=True)
                if item.get('float_value') is not None:
                    embed.add_field(name="🔢 Float", value=f"{item['float_value']:.4f}", inline=True)
                embed.add_field(name="Previous Balance", value=f"${old_balance:,.2f}", inline=True)
                embed.add_field(name="New Balance", value=f"${new_balance:,.2f}", inline=True)
                embed.set_footer(text=f"💖 Support us: {KO_FI_URL} | 🌐 Dashboard: {DASHBOARD_URL}")

                await interaction.followup.send(embed=embed)

    except Exception as e:
        logger.error(f"Sell error: {e}")
        await interaction.followup.send(f"❌ Error selling item: {str(e)[:100]}", ephemeral=True)

# ============================================
# QUESTS COMMANDS
# ============================================

@bot.tree.command(name="quests", description="View your daily quests")
async def view_quests(interaction: discord.Interaction):
    if not await is_bot_channel(interaction):
        return

    await interaction.response.defer()

    user_id = interaction.user.id

    async with db_pool.acquire() as conn:
        await ensure_user_exists(user_id, interaction.user.display_name, conn)
        
        user = await conn.fetchrow("SELECT user_id FROM users WHERE user_id = $1", user_id)
        if not user:
            await conn.execute("INSERT INTO users (user_id, balance) VALUES ($1, $2)", user_id, 1000)
        
        quests = await conn.fetch("SELECT * FROM quests WHERE user_id = $1 AND claimed = false", user_id)
        if not quests:
            await create_daily_quests(user_id, conn)
            quests = await conn.fetch("SELECT * FROM quests WHERE user_id = $1 AND claimed = false", user_id)

        unique_quests = {}
        for quest in quests:
            if quest['quest_type'] not in unique_quests:
                unique_quests[quest['quest_type']] = quest

        embed = discord.Embed(title="📋 Daily Quests", color=discord.Color.purple(), timestamp=datetime.now())
        quest_names = {"open_cases": "🔑 Open Cases", "get_golds": "✨ Find Gold Items", "earn_money": "💰 Earn Money", "trade_up": "🔄 Complete Trade-Ups", "sell_items": "💸 Sell Items", "jackpot_win": "🎲 Win Jackpot", "daily_streak": "📅 Maintain Daily Streak"}
        completed_count = 0

        for quest_type, quest in unique_quests.items():
            name = quest_names.get(quest_type, quest_type)
            status = "✅ COMPLETED" if quest['completed'] else f"Progress: {quest['progress']}/{quest['required']}"
            embed.add_field(name=name, value=f"{status}\nReward: ${quest['reward']:,}", inline=False)
            if quest['completed']:
                completed_count += 1

        if completed_count == len(unique_quests):
            embed.set_footer(text="All quests completed! Use /claim to collect your rewards!")
        else:
            embed.set_footer(text=f"💖 Support us: {KO_FI_URL} | 🌐 Dashboard: {DASHBOARD_URL}")

        await interaction.followup.send(embed=embed)

@bot.tree.command(name="claim", description="Claim completed quest rewards")
async def claim_quests(interaction: discord.Interaction):
    if not await is_bot_channel(interaction):
        return

    await interaction.response.defer()

    user_id = interaction.user.id

    try:
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                await ensure_user_exists(user_id, interaction.user.display_name, conn)

                # Atomic claim: UPDATE ... RETURNING prevents double-payout from
                # concurrent requests (same TOCTOU fix as the web /api/claim endpoint).
                claimed = await conn.fetch(
                    "UPDATE quests SET claimed = true WHERE user_id = $1 AND completed = true AND claimed = false RETURNING reward",
                    user_id
                )
                if not claimed:
                    await interaction.followup.send("❌ No completed quests to claim!", ephemeral=True)
                    return

                total_reward = sum(r['reward'] for r in claimed)
                await conn.execute("UPDATE users SET balance = balance + $1 WHERE user_id = $2", total_reward, user_id)

                new_balance = await get_balance(user_id, conn)

                embed = discord.Embed(title="🎉 Quests Claimed!", color=discord.Color.green(), timestamp=datetime.now())
                embed.add_field(name="Total Reward", value=f"${total_reward:,.2f}", inline=False)
                embed.add_field(name="New Balance", value=f"${new_balance:,.2f}", inline=True)
                embed.set_footer(text=f"💖 Support us: {KO_FI_URL} | 🌐 Dashboard: {DASHBOARD_URL}")
                await interaction.followup.send(embed=embed)
    except Exception as e:
        logger.error(f"Claim quests error: {e}")
        await interaction.followup.send(f"❌ Error claiming quests: {str(e)[:100]}", ephemeral=True)

# ============================================
# LEADERBOARD COMMANDS
# ============================================

@bot.tree.command(name="leaderboard_money", description="View richest users")
async def lb_money(interaction: discord.Interaction):
    if not await is_bot_channel(interaction):
        return

    await interaction.response.defer()

    async with db_pool.acquire() as conn:
        top_users = await conn.fetch("SELECT user_id, balance FROM users ORDER BY balance DESC LIMIT 10")
        embed = discord.Embed(title="💰 Richest Users", color=discord.Color.gold())

        for idx, user in enumerate(top_users, 1):
            try:
                member = await bot.fetch_user(user['user_id'])
                medal = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"{idx}."
                embed.add_field(name=f"{medal} {member.display_name}", value=f"${user['balance']:,.2f}", inline=False)
            except:
                pass

        embed.set_footer(text=f"💖 Support us: {KO_FI_URL} | 🌐 Dashboard: {DASHBOARD_URL}")
        await interaction.followup.send(embed=embed)

@bot.tree.command(name="leaderboard_opens", description="View most cases opened")
async def lb_opens(interaction: discord.Interaction):
    if not await is_bot_channel(interaction):
        return

    await interaction.response.defer()

    async with db_pool.acquire() as conn:
        top_users = await conn.fetch("SELECT user_id, total_opens FROM users ORDER BY total_opens DESC LIMIT 10")
        embed = discord.Embed(title="🔑 Most Cases Opened", color=discord.Color.blue())

        for idx, user in enumerate(top_users, 1):
            if user['total_opens'] > 0:
                try:
                    member = await bot.fetch_user(user['user_id'])
                    medal = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"{idx}."
                    embed.add_field(name=f"{medal} {member.display_name}", value=f"{user['total_opens']} cases", inline=False)
                except:
                    pass

        embed.set_footer(text=f"💖 Support us: {KO_FI_URL} | 🌐 Dashboard: {DASHBOARD_URL}")
        await interaction.followup.send(embed=embed)

@bot.tree.command(name="leaderboard_golds", description="View most gold items found")
async def lb_golds(interaction: discord.Interaction):
    if not await is_bot_channel(interaction):
        return

    await interaction.response.defer()

    async with db_pool.acquire() as conn:
        top_users = await conn.fetch("SELECT user_id, total_golds FROM users ORDER BY total_golds DESC LIMIT 10")
        embed = discord.Embed(title="✨ Most Gold Items", color=discord.Color.gold())

        for idx, user in enumerate(top_users, 1):
            if user['total_golds'] > 0:
                try:
                    member = await bot.fetch_user(user['user_id'])
                    medal = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"{idx}."
                    embed.add_field(name=f"{medal} {member.display_name}", value=f"{user['total_golds']} golds", inline=False)
                except:
                    pass

        embed.set_footer(text=f"💖 Support us: {KO_FI_URL} | 🌐 Dashboard: {DASHBOARD_URL}")
        await interaction.followup.send(embed=embed)

@bot.tree.command(name="leaderboard_trades", description="View most trade-ups completed")
async def lb_trades(interaction: discord.Interaction):
    if not await is_bot_channel(interaction):
        return

    await interaction.response.defer()

    async with db_pool.acquire() as conn:
        top_users = await conn.fetch("SELECT user_id, total_trades FROM users ORDER BY total_trades DESC LIMIT 10")
        embed = discord.Embed(title="🔄 Most Trade-Ups", color=discord.Color.purple())

        for idx, user in enumerate(top_users, 1):
            if user['total_trades'] > 0:
                try:
                    member = await bot.fetch_user(user['user_id'])
                    medal = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"{idx}."
                    embed.add_field(name=f"{medal} {member.display_name}", value=f"{user['total_trades']} trades", inline=False)
                except:
                    pass

        embed.set_footer(text=f"💖 Support us: {KO_FI_URL} | 🌐 Dashboard: {DASHBOARD_URL}")
        await interaction.followup.send(embed=embed)

# ============================================
# JACKPOT COMMANDS
# ============================================

@bot.tree.command(name="jackpot", description="Join the jackpot (minimum $100)")
async def jackpot(interaction: discord.Interaction, amount: float):
    if not await is_bot_channel(interaction):
        return

    if amount < 100:
        await interaction.response.send_message("❌ Minimum bet is $100!", ephemeral=True)
        return

    await interaction.response.defer()

    await ensure_user_exists(interaction.user.id, interaction.user.display_name)

    # Fix 3 + Fix 7: DB-backed entry; determine winner inside lock but send outside
    winner_id = None
    win_amount = 0
    pot_total = 0.0

    async with jackpot_lock:
        success = await jackpot_enter(interaction.user.id, amount)
        if not success:
            await interaction.followup.send("❌ Insufficient balance!", ephemeral=True)
            return

        # Read current state to decide if jackpot should draw
        async with db_pool.acquire() as conn:
            pot_row    = await conn.fetchrow("SELECT pot FROM jackpot_state WHERE id = 1")
            entry_count = await conn.fetchval("SELECT COUNT(*) FROM jackpot_entries")
            pot_total   = float(pot_row['pot']) if pot_row else 0.0

        should_draw = entry_count >= 3 or pot_total >= 5000

        if should_draw:
            # Fix 7: draw winner inside lock (DB txn), then release before sending
            winner_id, win_amount, pot_total = await jackpot_draw()
            if winner_id:
                async with db_pool.acquire() as conn:
                    await update_quest_progress(winner_id, "jackpot_win", 1, conn)

    # Network I/O is now OUTSIDE the lock (Fix 7)
    if winner_id:
        try:
            winner_user = await bot.fetch_user(winner_id)
            winner_name = winner_user.display_name
        except Exception:
            winner_name = str(winner_id)

        winner_embed = discord.Embed(title="🏆 JACKPOT WINNER!", color=discord.Color.gold())
        winner_embed.add_field(name="Winner", value=winner_name, inline=False)
        winner_embed.add_field(name="Won",       value=f"${win_amount:,.2f}", inline=True)
        winner_embed.add_field(name="Total Pot", value=f"${pot_total:,.2f}",  inline=True)
        winner_embed.set_footer(text=f"💖 Support us: {KO_FI_URL} | 🌐 Dashboard: {DASHBOARD_URL}")
        await interaction.followup.send(embed=winner_embed)
    else:
        # Still gathering entries
        async with db_pool.acquire() as conn:
            pot_row    = await conn.fetchrow("SELECT pot FROM jackpot_state WHERE id = 1")
            entry_count = await conn.fetchval("SELECT COUNT(*) FROM jackpot_entries")
            pot_total   = float(pot_row['pot']) if pot_row else 0.0

        embed = discord.Embed(title="🎲 Joined Jackpot!", color=discord.Color.green())
        embed.add_field(name="Your Bet",       value=f"${amount:,.2f}",   inline=True)
        embed.add_field(name="Total Pot",      value=f"${pot_total:,.2f}", inline=True)
        embed.add_field(name="Total Players",  value=str(entry_count),    inline=True)
        embed.set_footer(text=f"💖 Support us: {KO_FI_URL} | 🌐 Dashboard: {DASHBOARD_URL}")
        await interaction.followup.send(embed=embed)

# ============================================
# TRADE-UP COMMANDS
# ============================================

# ============================================
# TRADE-UP COMMANDS  (Fix 15: unified helper)
# ============================================

async def _run_tradeup(
    interaction: discord.Interaction,
    input_rarity: str,
    required_count: int = 10
):
    """
    Fix 2 + Fix 15: Generic trade-up with FOR UPDATE SKIP LOCKED to prevent
    race conditions, and a single code path for all rarity levels.
    """
    output_rarity = TRADE_UP_PROGRESSION.get(input_rarity)
    if not output_rarity:
        await interaction.response.send_message("❌ Invalid rarity for trade-up.", ephemeral=True)
        return

    await interaction.response.defer()

    try:
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                await ensure_user_exists(interaction.user.id, interaction.user.display_name, conn)

                # Fix 2: Lock rows before reading to prevent concurrent double-spend
                items = await conn.fetch("""
                    SELECT id, item_name, price FROM inventory
                    WHERE user_id = $1 AND rarity = $2 AND status = 'kept'
                    ORDER BY price ASC
                    LIMIT $3
                    FOR UPDATE SKIP LOCKED
                """, interaction.user.id, input_rarity, required_count)

                if len(items) < required_count:
                    await interaction.followup.send(
                        f"❌ You need {required_count} {input_rarity} items. You only have {len(items)} available.",
                        ephemeral=True
                    )
                    return

                item_ids_to_delete = [r['id'] for r in items]
                await conn.execute("DELETE FROM inventory WHERE id = ANY($1::int[])", item_ids_to_delete)

                # Generate result item using secure RNG (Fix 1)
                possible_items = [
                    i for case in CASES.values()
                    for i in case['items'] if i['rarity'] == output_rarity
                ]
                if not possible_items:
                    possible_items = [{"name": f"Mystery {output_rarity} Item", "condition": "Field-Tested", "tier": None}]

                new_item_template = secure_choice(possible_items)
                float_value       = generate_skin_float()
                condition         = get_skin_condition(float_value)
                is_stattrak       = secure_random() < 0.1
                new_value         = calculate_item_value(output_rarity, condition, None, is_stattrak)
                name              = f"{'StatTrak™ ' if is_stattrak else ''}{new_item_template['name']}"

                await conn.execute("""
                    INSERT INTO inventory
                        (user_id, item_name, item_type, rarity, price, condition, is_stattrak, float_value)
                    VALUES ($1, $2, 'weapon', $3, $4, $5, $6, $7)
                """, interaction.user.id, name, output_rarity, new_value, condition, is_stattrak, float_value)
                await conn.execute(
                    "UPDATE users SET total_trades = total_trades + 1 WHERE user_id = $1",
                    interaction.user.id
                )
                await update_quest_progress(interaction.user.id, "trade_up", 1, conn)

        rarity_emoji = RARITY_EMOJIS.get(output_rarity, "")
        embed = discord.Embed(
            title=f"🔄 Trade-Up Complete! ({input_rarity} → {output_rarity})",
            color=discord.Color.purple()
        )
        embed.add_field(name="Received",    value=f"{rarity_emoji} **{name}**", inline=False)
        embed.add_field(name="Rarity",      value=f"{rarity_emoji} {output_rarity}", inline=True)
        embed.add_field(name="🔢 Float",    value=f"{float_value:.4f}",  inline=True)
        embed.add_field(name="Value",       value=f"${new_value:,.2f}",  inline=True)
        if is_stattrak:
            embed.add_field(name="🔥 StatTrak™", value="Rare variant!", inline=False)
        embed.set_footer(text=f"💖 Support us: {KO_FI_URL} | 🌐 Dashboard: {DASHBOARD_URL}")
        await interaction.followup.send(embed=embed)

    except Exception as e:
        logger.error(f"Tradeup error ({input_rarity}→{output_rarity}): {e}")
        await interaction.followup.send(f"❌ Error during trade-up: {str(e)[:100]}", ephemeral=True)

@bot.tree.command(name="tradeup", description="Trade 10 Blue weapons for 1 Purple weapon")
async def tradeup_weapons(interaction: discord.Interaction, item_ids: str):
    if not await is_bot_channel(interaction):
        return
    await _run_tradeup(interaction, "Blue")

@bot.tree.command(name="tradeup_purple", description="Trade 10 Purple weapons for 1 Pink weapon")
async def tradeup_purple(interaction: discord.Interaction, item_ids: str):
    if not await is_bot_channel(interaction):
        return
    await _run_tradeup(interaction, "Purple")

@bot.tree.command(name="tradeup_pink", description="Trade 10 Pink weapons for 1 Red weapon")
async def tradeup_pink(interaction: discord.Interaction, item_ids: str):
    if not await is_bot_channel(interaction):
        return
    await _run_tradeup(interaction, "Pink")

# ============================================
# GOLD TRADE COMMAND  (Fix 2 + Fix 13)
# ============================================

@bot.tree.command(name="goldtrade", description="Trade gold items for higher tier (5 items)")
async def gold_tradeup(interaction: discord.Interaction, item_ids: str):
    if not await is_bot_channel(interaction):
        return

    await interaction.response.defer()

    try:
        ids = [int(x.strip()) for x in item_ids.split(',')]
    except Exception:
        await interaction.followup.send("❌ Please provide comma-separated item IDs! Example: `/goldtrade 1,2,3,4,5`", ephemeral=True)
        return

    if len(ids) != 5:
        await interaction.followup.send("❌ You need exactly 5 gold items to trade up!", ephemeral=True)
        return

    try:
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                await ensure_user_exists(interaction.user.id, interaction.user.display_name, conn)

                # Fix 2: FOR UPDATE SKIP LOCKED prevents concurrent double-spend
                items = await conn.fetch("""
                    SELECT id, tier FROM inventory
                    WHERE id = ANY($1::int[]) AND user_id = $2
                      AND rarity = 'Gold' AND status = 'kept'
                    FOR UPDATE SKIP LOCKED
                """, ids, interaction.user.id)

                if len(items) < 5:
                    await interaction.followup.send(
                        f"❌ Only {len(items)} of those Gold items are available (concurrent conflict or wrong IDs).",
                        ephemeral=True
                    )
                    return

                # Fix 13: Infer next tier from input items (was always 'Rare' before)
                input_tiers = [item.get('tier', 'Common') for item in items]
                valid_tiers = [t for t in input_tiers if t in GOLD_TIER_PROGRESSION]
                if not valid_tiers:
                    await interaction.followup.send("❌ No valid gold tier found in input items.", ephemeral=True)
                    return

                tier_index = max(GOLD_TIER_PROGRESSION.index(t) for t in valid_tiers)
                if tier_index + 1 >= len(GOLD_TIER_PROGRESSION):
                    await interaction.followup.send("❌ Cannot trade up — already at maximum tier (Mythic)!", ephemeral=True)
                    return

                next_tier = GOLD_TIER_PROGRESSION[tier_index + 1]

                item_ids_to_delete = [r['id'] for r in items]
                await conn.execute("DELETE FROM inventory WHERE id = ANY($1::int[])", item_ids_to_delete)

                # Fix 1: Use secure RNG
                is_stattrak        = secure_random() < 0.1
                float_value        = generate_skin_float()
                condition_from_float = get_skin_condition(float_value)
                new_value          = calculate_item_value("Gold", condition_from_float, next_tier, is_stattrak)
                name               = f"{'StatTrak™ ' if is_stattrak else ''}{next_tier} Gold Item"

                await conn.execute("""
                    INSERT INTO inventory
                        (user_id, item_name, item_type, rarity, price, condition, is_stattrak, float_value)
                    VALUES ($1, $2, 'weapon', 'Gold', $3, $4, $5, $6)
                """, interaction.user.id, name, new_value, condition_from_float, is_stattrak, float_value)
                await conn.execute("UPDATE users SET total_trades = total_trades + 1 WHERE user_id = $1", interaction.user.id)
                await update_quest_progress(interaction.user.id, "trade_up", 1, conn)

        embed = discord.Embed(title="🔄 Gold Trade-Up Complete!", color=discord.Color.gold())
        embed.add_field(name="Received",  value=f"⭐ **{name}**",         inline=False)
        embed.add_field(name="Tier",      value=next_tier,                 inline=True)
        embed.add_field(name="🔢 Float",  value=f"{float_value:.4f}",     inline=True)
        embed.add_field(name="Value",     value=f"${new_value:,.2f}",      inline=True)
        embed.set_footer(text=f"💖 Support us: {KO_FI_URL} | 🌐 Dashboard: {DASHBOARD_URL}")
        await interaction.followup.send(embed=embed)

    except Exception as e:
        logger.error(f"Gold trade error: {e}")
        await interaction.followup.send(f"❌ Error during gold trade: {str(e)[:100]}", ephemeral=True)

# ============================================
# STICKER TRADE COMMAND
# ============================================

@bot.tree.command(name="stickertrade", description="Trade stickers for higher rarity (5 items)")
async def sticker_tradeup(interaction: discord.Interaction, item_ids: str):
    if not await is_bot_channel(interaction):
        return

    await interaction.response.defer()

    try:
        ids = [int(x.strip()) for x in item_ids.split(',')]
    except:
        await interaction.followup.send("❌ Please provide comma-separated item IDs! Example: `/stickertrade 1,2,3,4,5`", ephemeral=True)
        return

    if len(ids) != 5:
        await interaction.followup.send("❌ You need exactly 5 stickers to trade up!", ephemeral=True)
        return

    try:
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                await ensure_user_exists(interaction.user.id, interaction.user.display_name, conn)
                
                items = await conn.fetch(
                    "SELECT * FROM inventory WHERE id = ANY($1::int[]) AND user_id = $2 AND item_type = 'sticker' AND status = 'kept' FOR UPDATE",
                    ids, interaction.user.id
                )
                if len(items) != len(ids):
                    await interaction.followup.send("❌ One or more items not found or not a sticker in your inventory!", ephemeral=True)
                    return
                rarities = [item['rarity'] for item in items]

                rarity_order = list(STICKER_TRADE_PROGRESSION.keys())
                current_rarity = None
                for r in rarities:
                    if r in rarity_order:
                        if current_rarity is None or rarity_order.index(r) > rarity_order.index(current_rarity):
                            current_rarity = r

                if current_rarity is None or current_rarity not in STICKER_TRADE_PROGRESSION:
                    await interaction.followup.send(f"❌ Cannot trade up these stickers!", ephemeral=True)
                    return

                next_rarity = STICKER_TRADE_PROGRESSION[current_rarity]

                for item in items:
                    await conn.execute("DELETE FROM inventory WHERE id = $1", item['id'])

                is_stattrak = secure_random() < 0.1
                new_value = calculate_item_value(next_rarity, None, None, is_stattrak)
                name = f"{'StatTrak™ ' if is_stattrak else ''}Mystery {next_rarity} Sticker"

                await conn.execute("INSERT INTO inventory (user_id, item_name, item_type, rarity, price, is_stattrak) VALUES ($1, $2, 'sticker', $3, $4, $5)",
                                  interaction.user.id, name, next_rarity, new_value, is_stattrak)
                await conn.execute("UPDATE users SET total_trades = total_trades + 1 WHERE user_id = $1", interaction.user.id)
                await update_quest_progress(interaction.user.id, "trade_up", 1, conn)

                embed = discord.Embed(title="🔄 Sticker Trade-Up Complete!", color=discord.Color.purple())
                embed.add_field(name="Traded Items (IDs)", value=", ".join(str(id) for id in ids), inline=False)
                embed.add_field(name="Received", value=f"**{name}**", inline=False)
                embed.add_field(name="Rarity", value=next_rarity, inline=True)
                embed.add_field(name="Value", value=f"${new_value:,.2f}", inline=True)
                embed.set_footer(text=f"💖 Support us: {KO_FI_URL} | 🌐 Dashboard: {DASHBOARD_URL}")
                await interaction.followup.send(embed=embed)
    except Exception as e:
        logger.error(f"Sticker trade error: {e}")
        await interaction.followup.send(f"❌ Error during sticker trade: {str(e)[:100]}", ephemeral=True)

# ============================================
# QUICK TRADE COMMAND
# ============================================

@bot.tree.command(name="quicktrade", description="Quick trade-up - randomly selects items from your inventory")
async def quick_tradeup(interaction: discord.Interaction, rarity: str):
    if not await is_bot_channel(interaction):
        return

    await interaction.response.defer()

    rarity_map = {
        'blue': {'rarity': 'Blue', 'next': 'Purple', 'count': 10, 'emoji': '🟦'},
        'purple': {'rarity': 'Purple', 'next': 'Pink', 'count': 10, 'emoji': '🟪'},
        'pink': {'rarity': 'Pink', 'next': 'Red', 'count': 10, 'emoji': '💗'}
    }

    if rarity.lower() not in rarity_map:
        await interaction.followup.send("❌ Invalid rarity! Use: `blue`, `purple`, or `pink`", ephemeral=True)
        return

    config = rarity_map[rarity.lower()]

    try:
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                await ensure_user_exists(interaction.user.id, interaction.user.display_name, conn)
                
                items = await conn.fetch(
                    "SELECT id, item_name FROM inventory WHERE user_id = $1 AND rarity = $2 AND item_type = 'weapon' AND status = 'kept' FOR UPDATE",
                    interaction.user.id, config['rarity']
                )

                if len(items) < config['count']:
                    await interaction.followup.send(f"❌ You need {config['count']} {config['rarity']} items for trade-up! You have {len(items)}.", ephemeral=True)
                    return

                selected_items = secure_shuffle(list(items))[:config["count"]]
                selected_ids = [item['id'] for item in selected_items]

                for item_id in selected_ids:
                    await conn.execute("DELETE FROM inventory WHERE id = $1", item_id)

                is_stattrak = secure_random() < 0.1
                possible_items = []
                for case in CASES.values():
                    for item in case['items']:
                        if item['rarity'] == config['next']:
                            possible_items.append(item)

                if not possible_items:
                    possible_items = [{"name": f"Mystery {config['next']} Item", "condition": "Field-Tested"}]

                new_item_template = secure_choice(possible_items)
                condition = new_item_template.get('condition', 'Field-Tested')
                
                float_value = generate_skin_float()
                condition_from_float = get_skin_condition(float_value)
                
                new_value = calculate_item_value(config['next'], condition, None, is_stattrak)
                float_multiplier = {
                    "Factory New": 2.0,
                    "Minimal Wear": 1.5,
                    "Field-Tested": 1.0,
                    "Well-Worn": 0.75,
                    "Battle-Scarred": 0.5
                }.get(condition_from_float, 1.0)
                new_value = round(new_value * float_multiplier, 2)
                
                name = f"{'StatTrak™ ' if is_stattrak else ''}{new_item_template['name']}"

                await conn.execute("""INSERT INTO inventory 
                    (user_id, item_name, item_type, rarity, price, condition, is_stattrak, float_value) 
                    VALUES ($1, $2, 'weapon', $3, $4, $5, $6, $7)""",
                    interaction.user.id, name, config['next'], new_value, condition_from_float, is_stattrak, float_value)
                await conn.execute("UPDATE users SET total_trades = total_trades + 1 WHERE user_id = $1", interaction.user.id)
                await update_quest_progress(interaction.user.id, "trade_up", 1, conn)

                rarity_emoji = RARITY_EMOJIS.get(config['next'], config['emoji'])

                embed = discord.Embed(title=f"🔄 Quick Trade-Up Complete! ({config['rarity']} → {config['next']})", color=discord.Color.purple())
                embed.add_field(name="Traded Items", value=f"{config['count']} random {config['rarity']} items", inline=False)
                embed.add_field(name="Traded IDs", value=", ".join(str(id) for id in selected_ids), inline=False)
                embed.add_field(name="Received", value=f"{rarity_emoji} **{name}**", inline=False)
                embed.add_field(name="Rarity", value=f"{rarity_emoji} {config['next']}", inline=True)
                embed.add_field(name="🔢 Float", value=f"{float_value:.4f}", inline=True)
                embed.add_field(name="Value", value=f"${new_value:,.2f}", inline=True)
                if is_stattrak:
                    embed.add_field(name="🔥 StatTrak™", value="Rare variant!", inline=False)
                embed.set_footer(text=f"💖 Support us: {KO_FI_URL} | 🌐 Dashboard: {DASHBOARD_URL}")

                await interaction.followup.send(embed=embed)
    except Exception as e:
        logger.error(f"Quick trade error: {e}")
        await interaction.followup.send(f"❌ Error during trade-up: {str(e)[:100]}", ephemeral=True)

# ============================================
# ADMIN STATS COMMAND
# ============================================

@bot.tree.command(name="stats", description="View bot statistics (Admin only)")
@app_commands.default_permissions(administrator=True)
async def bot_stats(interaction: discord.Interaction):
    if not await is_bot_channel(interaction):
        return

    await interaction.response.defer()

    try:
        async with db_pool.acquire() as conn:
            total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
            total_balance = await conn.fetchval("SELECT COALESCE(SUM(balance), 0) FROM users")
            total_opens = await conn.fetchval("SELECT COALESCE(SUM(total_opens), 0) FROM users")
            total_golds = await conn.fetchval("SELECT COALESCE(SUM(total_golds), 0) FROM users")
            total_trades = await conn.fetchval("SELECT COALESCE(SUM(total_trades), 0) FROM users")

            most_valuable = await conn.fetchrow("SELECT item_name, price FROM inventory WHERE price IS NOT NULL ORDER BY price DESC LIMIT 1")
            total_inv_value = await conn.fetchval("SELECT COALESCE(SUM(price), 0) FROM inventory WHERE status = 'kept'")

            embed = discord.Embed(title="📊 Bot Statistics", color=discord.Color.blue(), timestamp=datetime.now())
            embed.add_field(name="👥 Total Users", value=f"{total_users:,}", inline=True)
            embed.add_field(name="💰 Total Economy Balance", value=f"${float(total_balance):,.2f}", inline=True)
            embed.add_field(name="📦 Total Cases Opened", value=f"{total_opens:,}", inline=True)
            embed.add_field(name="✨ Total Golds Found", value=f"{total_golds:,}", inline=True)
            embed.add_field(name="🔄 Total Trade-Ups", value=f"{total_trades:,}", inline=True)
            embed.add_field(name="💎 Total Inventory Value", value=f"${float(total_inv_value):,.2f}", inline=True)

            if most_valuable and most_valuable['item_name']:
                embed.add_field(name="🏆 Most Valuable Item", value=f"{most_valuable['item_name']} (${float(most_valuable['price']):,.2f})", inline=False)

            embed.set_footer(text=f"💖 Support us: {KO_FI_URL} | 🌐 Dashboard: {DASHBOARD_URL}")
            await interaction.followup.send(embed=embed)
    except Exception as e:
        logger.error(f"Stats error: {e}")
        await interaction.followup.send(f"❌ Error fetching statistics: {str(e)[:100]}", ephemeral=True)

# ============================================
# GUILD SETTINGS COMMANDS
# ============================================

@bot.tree.command(name="setchannel", description="Set the channel for bot commands (Admin only)")
@app_commands.default_permissions(administrator=True)
async def set_bot_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ You need Administrator permissions to use this command!", ephemeral=True)
        return
    
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO guild_settings (guild_id, name, bot_channel_id, updated_at)
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (guild_id) DO UPDATE SET
            bot_channel_id = $3, updated_at = NOW()
        """, interaction.guild_id, interaction.guild.name, channel.id)
    
    embed = discord.Embed(
        title="✅ Bot Channel Set!",
        description=f"Bot commands will now only work in {channel.mention}",
        color=discord.Color.green()
    )
    embed.set_footer(text=f"💖 Support us: {KO_FI_URL} | 🌐 Dashboard: {DASHBOARD_URL}")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="removechannel", description="Remove channel restriction (Admin only)")
@app_commands.default_permissions(administrator=True)
async def remove_bot_channel(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ You need Administrator permissions to use this command!", ephemeral=True)
        return
    
    async with db_pool.acquire() as conn:
        await conn.execute("""
            UPDATE guild_settings SET bot_channel_id = NULL, updated_at = NOW() WHERE guild_id = $1
        """, interaction.guild_id)
    
    embed = discord.Embed(
        title="✅ Channel Restriction Removed!",
        description="Bot commands can now be used in any channel",
        color=discord.Color.green()
    )
    embed.set_footer(text=f"💖 Support us: {KO_FI_URL} | 🌐 Dashboard: {DASHBOARD_URL}")
    await interaction.response.send_message(embed=embed)

# ============================================
# GIVEAWAY COMMANDS
# ============================================

@bot.tree.command(name="giveaway_create", description="Create a giveaway (Admin only)")
@app_commands.default_permissions(administrator=True)
async def create_giveaway(interaction: discord.Interaction, prize: str, duration_minutes: int, winners: int = 1):
    if not await is_bot_channel(interaction):
        return

    if duration_minutes < 1 or duration_minutes > 10080:
        await interaction.response.send_message("❌ Duration must be between 1 minute and 7 days!", ephemeral=True)
        return
    if winners < 1 or winners > 10:
        await interaction.response.send_message("❌ Winners must be between 1 and 10!", ephemeral=True)
        return

    await interaction.response.defer()

    end_time = datetime.now() + timedelta(minutes=duration_minutes)
    embed = discord.Embed(title="🎉 GIVEAWAY! 🎉", color=discord.Color.gold(), timestamp=datetime.now())
    embed.add_field(name="Prize", value=prize, inline=False)
    embed.add_field(name="Winners", value=winners, inline=True)
    embed.add_field(name="Ends", value=f"<t:{int(end_time.timestamp())}:R>", inline=True)
    embed.add_field(name="How to Enter", value="Click the 🎉 button below!", inline=False)
    embed.set_footer(text=f"💖 Support us: {KO_FI_URL} | 🌐 Dashboard: {DASHBOARD_URL}")

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            giveaway_id_result = await conn.fetchrow(
                "INSERT INTO giveaways (message_id, channel_id, prize, winner_count, end_time) VALUES ($1, $2, $3, $4, $5) RETURNING id",
                0, interaction.channel_id, prize, winners, end_time
            )
            giveaway_id = giveaway_id_result['id']

    view = discord.ui.View(timeout=duration_minutes * 60)
    button = discord.ui.Button(emoji="🎉", label="Enter Giveaway", style=discord.ButtonStyle.primary)

    async def button_callback(button_interaction: discord.Interaction):
        async with db_pool.acquire() as conn:
            await ensure_user_exists(button_interaction.user.id, button_interaction.user.display_name, conn)
            result = await conn.execute(
                "INSERT INTO giveaway_entries (giveaway_id, user_id) VALUES ($1, $2) ON CONFLICT (giveaway_id, user_id) DO NOTHING",
                giveaway_id, button_interaction.user.id
            )
        if result == "INSERT 0 0":
            await button_interaction.response.send_message("❌ You already entered this giveaway!", ephemeral=True)
        else:
            await button_interaction.response.send_message("✅ You entered the giveaway! Good luck!", ephemeral=True)

    button.callback = button_callback
    view.add_item(button)
    await interaction.followup.send(embed=embed, view=view)
    msg = await interaction.original_response()

    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE giveaways SET message_id = $1 WHERE id = $2", msg.id, giveaway_id)

    asyncio.create_task(_run_giveaway(giveaway_id, duration_minutes * 60))


async def _run_giveaway(giveaway_id: int, delay_seconds: float):
    """Run a single giveaway — safe to call at startup for recovery."""
    if delay_seconds > 0:
        await asyncio.sleep(delay_seconds)
    async with db_pool.acquire() as conn:
        # Atomic claim: only one concurrent caller (timer vs startup recovery) wins;
        # the second sees no row returned and exits early.
        giveaway = await conn.fetchrow(
            "UPDATE giveaways SET ended = true WHERE id = $1 AND ended = false RETURNING *",
            giveaway_id
        )
        if not giveaway:
            return
        channel = bot.get_channel(giveaway['channel_id'])
        if channel is None:
            return
        entries = await conn.fetch("SELECT user_id FROM giveaway_entries WHERE giveaway_id = $1", giveaway_id)
        if not entries:
            await channel.send(f"🎉 Giveaway for **{giveaway['prize']}** ended with no entries!")
        else:
            winners_list = secure_shuffle([e['user_id'] for e in entries])[:min(giveaway['winner_count'], len(entries))]
            winner_mentions = []
            for winner_id in winners_list:
                try:
                    user = await bot.fetch_user(winner_id)
                    winner_mentions.append(user.mention)
                except Exception:
                    winner_mentions.append(f"<@{winner_id}>")
            result_embed = discord.Embed(title="🏆 GIVEAWAY WINNERS! 🏆", color=discord.Color.gold())
            result_embed.add_field(name="Prize", value=giveaway['prize'], inline=False)
            result_embed.add_field(name="Winners", value=", ".join(winner_mentions), inline=False)
            result_embed.set_footer(text=f"💖 Support us: {KO_FI_URL} | 🌐 Dashboard: {DASHBOARD_URL}")
            await channel.send(embed=result_embed)

@bot.tree.command(name="giveaway_reroll", description="Reroll a giveaway (Admin only)")
@app_commands.default_permissions(administrator=True)
async def reroll_giveaway(interaction: discord.Interaction, giveaway_id: int):
    if not await is_bot_channel(interaction):
        return

    await interaction.response.defer()

    async with db_pool.acquire() as conn:
        giveaway = await conn.fetchrow("SELECT * FROM giveaways WHERE id = $1", giveaway_id)
        if not giveaway:
            await interaction.followup.send("❌ Giveaway not found!", ephemeral=True)
            return

        entries = await conn.fetch("SELECT user_id FROM giveaway_entries WHERE giveaway_id = $1", giveaway_id)
        if not entries:
            await interaction.followup.send("❌ No entries to reroll!", ephemeral=True)
            return

        new_winners = secure_shuffle([e['user_id'] for e in entries])[:min(giveaway['winner_count'], len(entries))]
        winner_mentions = []
        for winner_id in new_winners:
            try:
                user = await bot.fetch_user(winner_id)
                winner_mentions.append(user.mention)
            except Exception:
                winner_mentions.append(f"<@{winner_id}>")

        embed = discord.Embed(title="🔄 Giveaway Rerolled!", color=discord.Color.gold())
        embed.add_field(name="Prize", value=giveaway['prize'], inline=False)
        embed.add_field(name="New Winners", value=", ".join(winner_mentions), inline=False)
        embed.set_footer(text=f"💖 Support us: {KO_FI_URL} | 🌐 Dashboard: {DASHBOARD_URL}")
        await interaction.followup.send(embed=embed)

# ============================================
# DASHBOARD COMMAND
# ============================================

@bot.tree.command(name="dashboard", description="Get the link to the bot's web dashboard")
async def dashboard(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🌐 CS2CaseBot Dashboard",
        description="**Take your case opening experience to the next level!**",
        color=discord.Color.blue()
    )
    embed.add_field(
        name="🎰 Live Slot Machine Animation",
        value="Watch the reels spin with **realistic slot machine animations** as you open cases! Every pull feels like the real thing with smooth spinning and dramatic reveals.",
        inline=False
    )
    embed.add_field(
        name="✨ Premium Features",
        value="• **Live spinning reels** with authentic slot feel\n"
              "• **Real-time item reveals** with glow effects\n"
              "• **Confetti & particle bursts** on rare pulls\n"
              "• **Float values & conditions** for every skin\n"
              "• **Instant inventory management** with one click",
        inline=False
    )
    embed.add_field(
        name="🔗 Try It Now",
        value="[**Click here to open the dashboard → cs2casebot.xyz**](https://cs2casebot.xyz/)",
        inline=False
    )
    embed.set_footer(text="💖 Support us on Ko-fi")
    await interaction.response.send_message(embed=embed)

# ============================================
# HELP COMMAND
# ============================================

@bot.tree.command(name="help_bot", description="Show all bot commands")
async def help_command(interaction: discord.Interaction):
    if not await is_bot_channel(interaction):
        return

    await interaction.response.defer()

    embed = discord.Embed(title="🎮 CS2CaseBot Commands", color=discord.Color.blue())
    embed.add_field(name="💰 Economy", value="`/balance` `/daily` `/transfer`", inline=False)
    embed.add_field(name="📦 Cases (37)", value="`/cases` `/open <case>` `/bulkopen <case> 5/10/15/20/25`", inline=False)
    embed.add_field(name="⭐ Stickers (5)", value="`/capsules` `/sticker <capsule>`", inline=False)
    embed.add_field(name="🔄 Trade-Up", value="`/tradeup <ids>` (10 Blue→Purple)\n`/tradeup_purple <ids>` (10 Purple→Pink)\n`/tradeup_pink <ids>` (10 Pink→Red)\n`/quicktrade blue/purple/pink` (Random)\n`/goldtrade <ids>` (5 Golds)\n`/stickertrade <ids>` (5 stickers)", inline=False)
    embed.add_field(name="📋 Quests", value="`/quests` `/claim`", inline=False)
    embed.add_field(name="🎁 Giveaways", value="`/giveaway_create` `/giveaway_reroll` (Admin)", inline=False)
    embed.add_field(name="🎮 Inventory", value="`/inventory` `/sell <id>`", inline=False)
    embed.add_field(name="🏆 Leaderboards", value="`/leaderboard_money` `/leaderboard_opens` `/leaderboard_golds` `/leaderboard_trades`", inline=False)
    embed.add_field(name="🎲 Jackpot", value="`/jackpot <amount>`", inline=False)
    embed.add_field(name="🌐 Dashboard", value="`/dashboard`", inline=False)
    embed.add_field(name="📊 Admin", value="`/stats` `/setchannel` `/removechannel`", inline=False)
    embed.add_field(name="💎 Bulk Discounts", value="5:5%, 10:10%, 15:15%, 20:20%, 25:25%", inline=False)
    embed.add_field(name="💬 Join Our Community", value=f"[Click here to join our Discord!]({DISCORD_INVITE_URL})", inline=False)
    embed.set_footer(text=f"💖 Support us on Ko-fi: {KO_FI_URL} | 🌐 Dashboard: {DASHBOARD_URL}")
    await interaction.followup.send(embed=embed)

# ============================================
# GAME HELPER FUNCTIONS
# ============================================

async def get_username(user_id: int) -> str:
    """Get username from database or fetch from Discord"""
    try:
        async with db_pool.acquire() as conn:
            user = await conn.fetchrow("SELECT username FROM users WHERE user_id = $1", user_id)
            if user and user['username']:
                return user['username']
    except:
        pass
    
    try:
        discord_user = await bot.fetch_user(user_id)
        if discord_user:
            return discord_user.display_name
    except:
        pass
    
    return f"User_{user_id}"

async def create_coinflip_game(user_id: int, amount: float) -> dict:
    """Create a new coinflip game"""
    if amount < 100:
        return {'success': False, 'error': 'Minimum bet is $100'}
    
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            await ensure_user_exists(user_id, conn=conn)

            # Atomic deduct: WHERE balance >= $1 prevents negative balance under concurrency.
            deducted = await conn.fetchval(
                "UPDATE users SET balance = balance - $1 WHERE user_id = $2 AND balance >= $1 RETURNING balance",
                amount, user_id
            )
            if deducted is None:
                return {'success': False, 'error': 'Insufficient balance'}

            result = await conn.fetchrow(
                """INSERT INTO coinflip_games (creator_id, amount, status)
                   VALUES ($1, $2, 'waiting') RETURNING id""",
                user_id, amount
            )
            game_id = result['id']

            return {'success': True, 'game_id': game_id, 'amount': amount}

async def join_coinflip_game(game_id: int, user_id: int) -> dict:
    """Join an existing coinflip game"""
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            await ensure_user_exists(user_id, conn=conn)

            # FOR UPDATE locks the game row so two concurrent join requests can't
            # both see status='waiting' and both proceed to deduct + update the game.
            game = await conn.fetchrow(
                "SELECT * FROM coinflip_games WHERE id = $1 AND status = 'waiting' FOR UPDATE",
                game_id
            )
            if not game:
                return {'success': False, 'error': 'Game not found or already active'}

            if game['creator_id'] == user_id:
                return {'success': False, 'error': "You can't join your own game!"}

            # Atomic deduct: WHERE balance >= $1 prevents negative balance under concurrency.
            deducted = await conn.fetchval(
                "UPDATE users SET balance = balance - $1 WHERE user_id = $2 AND balance >= $1 RETURNING balance",
                game['amount'], user_id
            )
            if deducted is None:
                return {'success': False, 'error': 'Insufficient balance'}
            
            await conn.execute(
                """UPDATE coinflip_games SET opponent_id = $1, status = 'active' WHERE id = $2""",
                user_id, game_id
            )
            
            winner_id = secure_choice([game['creator_id'], user_id])
            win_amount = int(game['amount'] * 1.95)
            
            await conn.execute(
                "UPDATE users SET balance = balance + $1 WHERE user_id = $2",
                win_amount, winner_id
            )
            await conn.execute(
                "UPDATE coinflip_games SET winner_id = $1, completed_at = NOW(), status = 'complete' WHERE id = $2",
                winner_id, game_id
            )
            
            await update_quest_progress(winner_id, "jackpot_win", 1, conn)

            return {
                'success': True,
                'winner_id': winner_id,
                'amount': game['amount'],
                'win_amount': win_amount
            }

async def play_dice(user_id: int, amount: float, bet_type: str, bet_number: int) -> dict:
    """Play a dice game"""
    if amount < 100:
        return {'success': False, 'error': 'Minimum bet is $100'}
    if bet_type not in ['over', 'under']:
        return {'success': False, 'error': 'Bet type must be "over" or "under"'}
    if bet_number < 2 or bet_number > 99:
        return {'success': False, 'error': 'Bet number must be between 2 and 99'}
    
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            await ensure_user_exists(user_id, conn=conn)

            # Atomic deduct: WHERE balance >= $1 prevents negative balance under concurrency.
            deducted = await conn.fetchval(
                "UPDATE users SET balance = balance - $1 WHERE user_id = $2 AND balance >= $1 RETURNING balance",
                amount, user_id
            )
            if deducted is None:
                return {'success': False, 'error': 'Insufficient balance'}

            roll = secure_randint(1, 100)
            win = (roll > bet_number) if bet_type == 'over' else (roll < bet_number)
            
            if bet_type == 'over':
                multiplier = round(95 / (100 - bet_number), 2)
            else:
                multiplier = round(95 / (bet_number - 1), 2)
            
            win_amount = int(amount * multiplier) if win else 0
            
            if win:
                await conn.execute(
                    "UPDATE users SET balance = balance + $1 WHERE user_id = $2",
                    win_amount, user_id
                )
                await update_quest_progress(user_id, "earn_money", int(win_amount))
            
            await conn.execute(
                """INSERT INTO dice_games 
                   (user_id, amount, bet_type, bet_number, roll_number, result, multiplier) 
                   VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                user_id, amount, bet_type, bet_number, roll, 'win' if win else 'lose', multiplier
            )
            
            return {
                'success': True,
                'roll': roll,
                'bet_type': bet_type,
                'bet_number': bet_number,
                'win': win,
                'multiplier': multiplier,
                'amount': amount,
                'win_amount': win_amount
            }

# ============================================
# MINES GAME - COMPLETE FIXED VERSION
# ALL Decimal errors fixed!
# ============================================

async def start_mines_game(user_id: int, amount: float, grid_size: int = 5, mine_count: int = 3) -> dict:
    """Start a mines game"""
    if amount < 100:
        return {'success': False, 'error': 'Minimum bet is $100'}
    if grid_size not in [3, 4, 5, 6]:
        return {'success': False, 'error': 'Grid size must be 3, 4, 5, or 6'}
    
    max_mines = grid_size * grid_size - 2
    if mine_count < 1 or mine_count > max_mines:
        return {'success': False, 'error': f'Invalid mine count for {grid_size}x{grid_size} grid'}
    
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            await ensure_user_exists(user_id, conn=conn)

            # Atomic deduct: WHERE balance >= $1 prevents negative balance under concurrency.
            deducted = await conn.fetchval(
                "UPDATE users SET balance = balance - $1 WHERE user_id = $2 AND balance >= $1 RETURNING balance",
                amount, user_id
            )
            if deducted is None:
                return {'success': False, 'error': 'Insufficient balance'}

            total_tiles = grid_size * grid_size
            mine_positions = secure_shuffle(list(range(total_tiles)))[:mine_count]
            
            result = await conn.fetchrow(
                """INSERT INTO mines_games 
                   (user_id, bet_amount, grid_size, mine_count, status, mine_positions, revealed_tiles, multiplier) 
                   VALUES ($1, $2, $3, $4, 'active', $5, '{}', 1.0) 
                   RETURNING id""",
                user_id, amount, grid_size, mine_count, mine_positions
            )
            game_id = result['id']
            
            logger.info(f"🎮 Mines game created: ID={game_id}, User={user_id}, Amount=${amount}")
            
            return {
                'success': True,
                'game_id': game_id,
                'grid_size': grid_size,
                'mine_count': mine_count,
                'bet_amount': amount
            }


async def reveal_mines_tile(game_id: int, user_id: int, tile_index: int) -> dict:
    """Reveal a tile in a mines game - FIXED Decimal error!"""
    try:
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                await ensure_user_exists(user_id, conn=conn)
                
                # FOR UPDATE prevents two concurrent reveal requests from both
                # seeing the same game state and double-processing the same tile.
                game = await conn.fetchrow(
                    "SELECT * FROM mines_games WHERE id = $1 AND user_id = $2 FOR UPDATE",
                    game_id, user_id
                )
                
                if not game:
                    logger.warning(f"❌ Mines game {game_id} not found for user {user_id}")
                    return {'success': False, 'error': 'Game not found. Please start a new game with /mines'}
                
                # Check if game is still active
                if game['status'] != 'active':
                    status_msg = {
                        'won': 'You already won this game!',
                        'lost': 'You already lost this game!',
                        'cashed_out': 'You already cashed out!'
                    }.get(game['status'], f'Game status is {game["status"]}')
                    return {'success': False, 'error': status_msg}
                
                revealed = game['revealed_tiles'] or []
                if tile_index in revealed:
                    return {'success': False, 'error': 'Tile already revealed'}
                
                # Get mine positions
                mine_positions = game.get('mine_positions', [])
                if not mine_positions or len(mine_positions) == 0:
                    total_tiles = game['grid_size'] * game['grid_size']
                    mine_positions = secure_shuffle(list(range(total_tiles)))[:game['mine_count']]
                    await conn.execute(
                        "UPDATE mines_games SET mine_positions = $1 WHERE id = $2",
                        mine_positions, game_id
                    )
                
                # Check if hit a mine
                if tile_index in mine_positions:
                    await conn.execute(
                        "UPDATE mines_games SET exploded = true, status = 'lost' WHERE id = $1",
                        game_id
                    )
                    logger.info(f"💥 User {user_id} hit a mine in game {game_id}")
                    return {'success': False, 'exploded': True, 'message': '💥 BOOM! You hit a mine!'}
                
                # Reveal the tile
                revealed.append(tile_index)
                total_tiles = game['grid_size'] * game['grid_size']
                safe_tiles = total_tiles - game['mine_count']
                remaining = safe_tiles - len(revealed)
                multiplier = round(1 + (len(revealed) / safe_tiles) * 10, 2)
                
                # Check if all safe tiles are revealed (WIN!)
                if remaining <= 0:
                    # FIXED: Convert Decimal to float before multiplying
                    bet_amount = float(game['bet_amount'])
                    win_amount = int(bet_amount * multiplier)
                    
                    await conn.execute(
                        "UPDATE users SET balance = balance + $1 WHERE user_id = $2",
                        win_amount, user_id
                    )
                    await conn.execute(
                        "UPDATE mines_games SET status = 'won', multiplier = $1 WHERE id = $2",
                        multiplier, game_id
                    )
                    await update_quest_progress(user_id, "earn_money", int(win_amount))
                    logger.info(f"🎉 User {user_id} WON mines game {game_id}! Won ${win_amount}")
                    
                    return {
                        'success': True,
                        'game_won': True,
                        'win_amount': win_amount,
                        'multiplier': multiplier,
                        'revealed': revealed,
                        'remaining': 0
                    }
                
                # Update game state
                await conn.execute(
                    "UPDATE mines_games SET revealed_tiles = $1, multiplier = $2 WHERE id = $3",
                    revealed, multiplier, game_id
                )
                
                # FIXED: Convert Decimal to float before multiplying
                bet_amount = float(game['bet_amount'])
                cash_out_amount = int(bet_amount * multiplier)
                
                return {
                    'success': True,
                    'game_won': False,
                    'multiplier': multiplier,
                    'revealed': revealed,
                    'remaining': remaining,
                    'cash_out_amount': cash_out_amount
                }
    except Exception as e:
        logger.error(f"reveal_mines_tile error: {e}")
        return {'success': False, 'error': f'Error: {str(e)}'}


async def cashout_mines(game_id: int, user_id: int) -> dict:
    """Cash out a mines game"""
    try:
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                await ensure_user_exists(user_id, conn=conn)
                
                game = await conn.fetchrow(
                    "SELECT * FROM mines_games WHERE id = $1 AND user_id = $2 AND status = 'active' FOR UPDATE",
                    game_id, user_id
                )
                if not game:
                    return {'success': False, 'error': 'Game not found or already ended'}
                
                # FIXED: Convert Decimal to float
                multiplier = float(game['multiplier'] or 1.0)
                bet_amount = float(game['bet_amount'])
                win_amount = int(bet_amount * multiplier)
                
                await conn.execute(
                    "UPDATE users SET balance = balance + $1 WHERE user_id = $2",
                    win_amount, user_id
                )
                await conn.execute(
                    "UPDATE mines_games SET status = 'cashed_out', multiplier = $1 WHERE id = $2",
                    multiplier, game_id
                )
                
                await update_quest_progress(user_id, "earn_money", int(win_amount))
                
                logger.info(f"💰 User {user_id} cashed out mines game {game_id} for ${win_amount}")
                
                return {
                    'success': True,
                    'win_amount': win_amount,
                    'multiplier': multiplier
                }
    except Exception as e:
        logger.error(f"cashout_mines error: {e}")
        return {'success': False, 'error': f'Error: {str(e)}'}


@bot.tree.command(name="mines", description="Start a mines game")
async def cmd_mines(interaction: discord.Interaction, amount: float, grid_size: int = 5, mine_count: int = 3):
    if not await is_bot_channel(interaction):
        return
    
    await interaction.response.defer()
    
    logger.info(f"🎮 User {interaction.user.id} starting mines game with ${amount}")
    
    result = await start_mines_game(interaction.user.id, amount, grid_size, mine_count)
    
    if not result['success']:
        await interaction.followup.send(f"❌ {result['error']}", ephemeral=True)
        return
    
    total_tiles = grid_size * grid_size
    
    embed = discord.Embed(
        title="💣 Mines Game Started!",
        description=f"Bet: ${amount:,.2f}\nGrid: {grid_size}x{grid_size}\nMines: {mine_count}",
        color=discord.Color.purple()
    )
    embed.add_field(name="🎮 Game ID", value=f"`{result['game_id']}`", inline=False)
    embed.add_field(
        name="📖 How to Play", 
        value=f"Use `/mines_reveal game_id:{result['game_id']} tile:0` to reveal a tile!\nTile numbers go from 0 to {total_tiles - 1}",
        inline=False
    )
    embed.set_footer(text="💖 Support us on Ko-fi!")
    
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="mines_reveal", description="Reveal a tile in your mines game")
async def cmd_mines_reveal(interaction: discord.Interaction, game_id: int, tile: int):
    if not await is_bot_channel(interaction):
        return
    
    await interaction.response.defer()
    
    logger.info(f"🎮 User {interaction.user.id} revealing tile {tile} in game {game_id}")
    
    try:
        result = await reveal_mines_tile(game_id, interaction.user.id, tile)
        
        if not result['success']:
            if result.get('exploded'):
                embed = discord.Embed(
                    title="💥 BOOM!",
                    description="You hit a mine! Game over! 😢",
                    color=discord.Color.red()
                )
                await interaction.followup.send(embed=embed)
            else:
                await interaction.followup.send(f"❌ {result.get('error', 'Something went wrong')}", ephemeral=True)
            return
        
        if result.get('game_won'):
            embed = discord.Embed(
                title="🎉 MINES WON! 🎉",
                description=f"You revealed all safe tiles and won **${result['win_amount']:,.2f}**!",
                color=discord.Color.gold()
            )
            embed.add_field(name="Multiplier", value=f"{result['multiplier']}x", inline=True)
            embed.add_field(name="Tiles Revealed", value=str(len(result['revealed'])), inline=True)
            await interaction.followup.send(embed=embed)
            return
        
        embed = discord.Embed(
            title="✅ Tile Revealed!",
            color=discord.Color.green()
        )
        embed.add_field(name="Safe Tiles Remaining", value=str(result['remaining']), inline=True)
        embed.add_field(name="Current Multiplier", value=f"{result['multiplier']}x", inline=True)
        embed.add_field(name="💰 Cash Out Value", value=f"${result['cash_out_amount']:,.2f}", inline=True)
        embed.add_field(name="💡 Next Step", value="Use `/mines_cashout` to cash out or reveal another tile!", inline=False)
        embed.set_footer(text="💖 Support us on Ko-fi!")
        
        await interaction.followup.send(embed=embed)
    except Exception as e:
        logger.error(f"cmd_mines_reveal error: {e}")
        await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)


@bot.tree.command(name="mines_cashout", description="Cash out your mines game")
async def cmd_mines_cashout(interaction: discord.Interaction, game_id: int):
    if not await is_bot_channel(interaction):
        return
    
    await interaction.response.defer()
    
    logger.info(f"💰 User {interaction.user.id} cashing out mines game {game_id}")
    
    try:
        result = await cashout_mines(game_id, interaction.user.id)
        
        if not result['success']:
            await interaction.followup.send(f"❌ {result['error']}", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="💰 Mines Cashed Out!",
            description=f"You cashed out for **${result['win_amount']:,.2f}**!",
            color=discord.Color.green()
        )
        embed.add_field(name="Multiplier", value=f"{result['multiplier']}x", inline=True)
        embed.set_footer(text="💖 Support us on Ko-fi!")
        
        await interaction.followup.send(embed=embed)
    except Exception as e:
        logger.error(f"cmd_mines_cashout error: {e}")
        await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

# ============================================
# SLOTS HELPERS
# ============================================

SLOT_SYMBOLS = [
    {'emoji': '🍒', 'value': 1, 'name': 'Cherry'},
    {'emoji': '🍋', 'value': 2, 'name': 'Lemon'},
    {'emoji': '🍊', 'value': 3, 'name': 'Orange'},
    {'emoji': '🍇', 'value': 4, 'name': 'Grape'},
    {'emoji': '💎', 'value': 10, 'name': 'Diamond'},
    {'emoji': '7️⃣', 'value': 20, 'name': 'Seven'},
    {'emoji': '🎰', 'value': 50, 'name': 'Jackpot'},
]

SLOT_PAYOUTS = {
    '🍒🍒🍒': 3,
    '🍋🍋🍋': 5,
    '🍊🍊🍊': 8,
    '🍇🍇🍇': 12,
    '💎💎💎': 30,
    '7️⃣7️⃣7️⃣': 60,
    '🎰🎰🎰': 200
}

async def play_slots(user_id: int, amount: float) -> dict:
    """Play the slot machine"""
    if amount < 50:
        return {'success': False, 'error': 'Minimum bet is $50'}
    
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            await ensure_user_exists(user_id, conn=conn)

            # Atomic deduct: WHERE balance >= $1 prevents negative balance under concurrency.
            deducted = await conn.fetchval(
                "UPDATE users SET balance = balance - $1 WHERE user_id = $2 AND balance >= $1 RETURNING balance",
                amount, user_id
            )
            if deducted is None:
                return {'success': False, 'error': 'Insufficient balance'}

            symbols = [secure_choice(SLOT_SYMBOLS)['emoji'] for _ in range(3)]
            result_str = ''.join(symbols)
            multiplier = SLOT_PAYOUTS.get(result_str, 0)
            win_amount = int(amount * multiplier) if multiplier > 0 else 0
            win_amount = int(win_amount * 0.98)  # 2% house edge
            
            if multiplier == 0:
                for sym in SLOT_SYMBOLS:
                    if symbols.count(sym['emoji']) >= 2:
                        multiplier = sym['value'] / 2
                        win_amount = int(amount * multiplier)
                        break
            
            if win_amount > 0:
                await conn.execute(
                    "UPDATE users SET balance = balance + $1 WHERE user_id = $2",
                    win_amount, user_id
                )
                await update_quest_progress(user_id, "earn_money", int(win_amount))
            
            await conn.execute(
                """INSERT INTO slots_games 
                   (user_id, bet_amount, spin_result, multiplier, win_amount) 
                   VALUES ($1, $2, $3, $4, $5)""",
                user_id, amount, symbols, multiplier, win_amount
            )
            
            return {
                'success': True,
                'symbols': symbols,
                'result_str': result_str,
                'multiplier': multiplier,
                'win_amount': win_amount,
                'bet_amount': amount
            }

# ============================================
# COINFLIP COMMANDS - VS COMPUTER
# ============================================

@bot.tree.command(name="coinflip", description="Flip a coin against the computer!")
async def cmd_coinflip(interaction: discord.Interaction, amount: float):
    if not await is_bot_channel(interaction):
        return
    
    await interaction.response.defer()
    
    if amount < 100:
        await interaction.followup.send("❌ Minimum bet is $100!", ephemeral=True)
        return
    
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            await ensure_user_exists(interaction.user.id, interaction.user.display_name, conn)

            # Atomic deduct: WHERE balance >= $1 prevents negative balance under concurrency.
            deducted = await conn.fetchval(
                "UPDATE users SET balance = balance - $1 WHERE user_id = $2 AND balance >= $1 RETURNING balance",
                amount, interaction.user.id
            )
            if deducted is None:
                await interaction.followup.send("❌ Insufficient balance!", ephemeral=True)
                return
            
            # Computer flips coin - 50/50 chance
            user_wins = secure_random() < 0.5
            
            if user_wins:
                win_amount = int(amount * 1.95)  # 95% payout
                await conn.execute(
                    "UPDATE users SET balance = balance + $1 WHERE user_id = $2",
                    win_amount, interaction.user.id
                )
                result = "win"
                await update_quest_progress(interaction.user.id, "jackpot_win", 1)
            else:
                win_amount = 0
                result = "lose"
            
            # Save game record - opponent_id is NULL for VS Computer games
            await conn.execute(
                """INSERT INTO coinflip_games 
                   (creator_id, amount, status, completed_at, opponent_id, winner_id) 
                   VALUES ($1, $2, 'complete', NOW(), NULL, $3)""",
                interaction.user.id, amount, interaction.user.id if user_wins else None
            )
            
            embed = discord.Embed(
                title="🪙 Coinflip vs Computer!",
                color=discord.Color.gold() if user_wins else discord.Color.red()
            )
            embed.add_field(name="Your Bet", value=f"${amount:,.2f}", inline=True)
            embed.add_field(name="Result", value="🎉 YOU WON!" if user_wins else "😢 Computer Wins!", inline=True)
            if user_wins:
                embed.add_field(name="You Won", value=f"${win_amount:,.2f}", inline=True)
            embed.set_footer(text="💖 Support us on Ko-fi!")
            await interaction.followup.send(embed=embed)

# ============================================
# DICE COMMANDS
# ============================================

@bot.tree.command(name="dice", description="Play dice - bet over or under a number")
async def cmd_dice(interaction: discord.Interaction, amount: float, bet_type: str, bet_number: int):
    if not await is_bot_channel(interaction):
        return
    
    await interaction.response.defer()
    
    bet_type = bet_type.lower()
    
    result = await play_dice(interaction.user.id, amount, bet_type, bet_number)
    
    if not result['success']:
        await interaction.followup.send(f"❌ {result['error']}", ephemeral=True)
        return
    
    embed = discord.Embed(
        title="🎲 Dice Roll!",
        color=discord.Color.green() if result['win'] else discord.Color.red()
    )
    embed.add_field(name="Bet Amount", value=f"${result['amount']:,.2f}", inline=True)
    embed.add_field(name="Bet Type", value=result['bet_type'].upper(), inline=True)
    embed.add_field(name="Bet Number", value=str(result['bet_number']), inline=True)
    embed.add_field(name="Roll", value=str(result['roll']), inline=True)
    embed.add_field(name="Multiplier", value=f"{result['multiplier']}x", inline=True)
    
    if result['win']:
        embed.add_field(name="💰 Won", value=f"${result['win_amount']:,.2f}", inline=True)
    else:
        embed.add_field(name="❌ Lost", value=f"${result['amount']:,.2f}", inline=True)
    
    embed.set_footer(text="💖 Support us on Ko-fi!")
    await interaction.followup.send(embed=embed)

# ============================================
# SLOTS COMMANDS
# ============================================

@bot.tree.command(name="slots", description="Play the slot machine")
async def cmd_slots(interaction: discord.Interaction, amount: float):
    if not await is_bot_channel(interaction):
        return
    
    await interaction.response.defer()
    
    result = await play_slots(interaction.user.id, amount)
    
    if not result['success']:
        await interaction.followup.send(f"❌ {result['error']}", ephemeral=True)
        return
    
    symbols = ' '.join(result['symbols'])
    
    embed = discord.Embed(
        title="🎰 SLOTS!",
        description=f"**[ {symbols} ]**",
        color=discord.Color.green() if result['win_amount'] > 0 else discord.Color.red()
    )
    embed.add_field(name="Bet", value=f"${result['bet_amount']:,.2f}", inline=True)
    
    if result['win_amount'] > 0:
        embed.add_field(name="💰 Won", value=f"${result['win_amount']:,.2f}", inline=True)
        embed.add_field(name="Multiplier", value=f"{result['multiplier']}x", inline=True)
        embed.color = discord.Color.gold()
    else:
        embed.add_field(name="❌ Lost", value=f"${result['bet_amount']:,.2f}", inline=True)
    
    embed.set_footer(text="💖 Support us on Ko-fi!")
    await interaction.followup.send(embed=embed)

# ============================================
# SKIN UPGRADE COMMANDS
# ============================================

@bot.tree.command(name="upgrade", description="Attempt to upgrade a skin to the next rarity")
async def cmd_upgrade(interaction: discord.Interaction, item_id: int):
    if not await is_bot_channel(interaction):
        return
    
    await interaction.response.defer()
    
    result = await skin_upgrade(interaction.user.id, item_id)
    
    if not result['success']:
        await interaction.followup.send(f"❌ {result['error']}", ephemeral=True)
        return
    
    if result.get('upgraded'):
        embed = discord.Embed(
            title="⭐ UPGRADE SUCCESSFUL!",
            description=f"{result['old_item_name']} → {result['new_item_name']}",
            color=discord.Color.gold()
        )
        embed.add_field(name="New Rarity", value=result['new_rarity'], inline=True)
        embed.add_field(name="New Value", value=f"${result['new_price']:,.2f}", inline=True)
    else:
        embed = discord.Embed(
            title="💔 Upgrade Failed!",
            description=f"{result['old_item_name']} was lost in the upgrade attempt",
            color=discord.Color.red()
        )
        embed.add_field(name="Cost", value=f"${result['cost']:,.2f}", inline=True)
    
    embed.set_footer(text="💖 Support us on Ko-fi!")
    await interaction.followup.send(embed=embed)

# ============================================
# HOURLY & WEEKLY COMMANDS
# ============================================

@bot.tree.command(name="hourly", description="Claim your hourly reward")
async def cmd_hourly(interaction: discord.Interaction):
    if not await is_bot_channel(interaction):
        return
    
    await interaction.response.defer()
    
    result = await claim_hourly(interaction.user.id)
    
    if not result['success']:
        await interaction.followup.send(f"⏰ {result['error']}", ephemeral=True)
        return
    
    embed = discord.Embed(
        title="🕐 Hourly Claimed!",
        description=f"You received ${result['reward']:,.2f}!",
        color=discord.Color.green()
    )
    embed.add_field(name="Total Claims", value=str(result['total_claimed']), inline=True)
    embed.set_footer(text="Come back in 1 hour for more!")
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="weekly", description="Claim your weekly reward")
async def cmd_weekly(interaction: discord.Interaction):
    if not await is_bot_channel(interaction):
        return
    
    await interaction.response.defer()
    
    result = await claim_weekly(interaction.user.id)
    
    if not result['success']:
        await interaction.followup.send(f"📅 {result['error']}", ephemeral=True)
        return
    
    embed = discord.Embed(
        title="📅 Weekly Claimed!",
        description=f"You received ${result['reward']:,.2f}!",
        color=discord.Color.gold()
    )
    embed.add_field(name="Total Claims", value=str(result['total_claimed']), inline=True)
    embed.set_footer(text="Come back in 7 days for more!")
    await interaction.followup.send(embed=embed)

# ============================================
# XP COMMANDS
# ============================================

@bot.tree.command(name="profile", description="View your profile and XP")
async def cmd_profile(interaction: discord.Interaction):
    if not await is_bot_channel(interaction):
        return
    
    await interaction.response.defer()
    
    async with db_pool.acquire() as conn:
        await ensure_user_exists(interaction.user.id, interaction.user.display_name, conn)
        user = await conn.fetchrow(
            "SELECT xp, level, prestige, balance FROM users WHERE user_id = $1",
            interaction.user.id
        )
        if not user:
            await interaction.followup.send("❌ User not found!", ephemeral=True)
            return
    
    xp = user['xp'] or 0
    level = user['level'] or 1
    prestige = user['prestige'] or 0
    balance = user['balance'] or 0
    
    xp_needed = level * 50 + 100
    
    embed = discord.Embed(
        title=f"👤 {interaction.user.display_name}'s Profile",
        color=discord.Color.blue()
    )
    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    embed.add_field(name="Level", value=f"🎮 {level}", inline=True)
    embed.add_field(name="Prestige", value=f"🌟 {prestige}", inline=True)
    embed.add_field(name="XP", value=f"{xp:,} / {xp_needed:,}", inline=True)
    embed.add_field(name="💰 Balance", value=f"${balance:,.2f}", inline=True)
    
    progress = min(100, int((xp / xp_needed) * 100))
    bar_length = 20
    filled = int(progress / (100 / bar_length))
    bar = "█" * filled + "░" * (bar_length - filled)
    embed.add_field(name="Progress", value=f"`{bar}` {progress}%", inline=False)
    
    embed.set_footer(text="💖 Support us on Ko-fi!")
    await interaction.followup.send(embed=embed)

# ============================================
# HOURLY & WEEKLY CLAIMS
# ============================================

async def claim_hourly(user_id: int) -> dict:
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            await ensure_user_exists(user_id, conn=conn)
            # FOR UPDATE locks the row so concurrent claims queue up
            user = await conn.fetchrow(
                "SELECT last_hourly, total_hourly_claimed FROM users WHERE user_id = $1 FOR UPDATE",
                user_id
            )
            if not user:
                return {'success': False, 'error': 'User not found'}

            now = datetime.now()
            last_hourly = user['last_hourly']

            if last_hourly and (now - last_hourly).total_seconds() < 3600:
                remaining = 3600 - (now - last_hourly).total_seconds()
                minutes = int(remaining // 60)
                return {'success': False, 'error': f'Already claimed! Next claim in {minutes} minutes'}

            reward = 75
            total_claimed = (user['total_hourly_claimed'] or 0) + 1

            if total_claimed % 10 == 0:
                reward += 250

            await conn.execute(
                """UPDATE users
                   SET balance = balance + $1, last_hourly = $2, total_hourly_claimed = $3
                   WHERE user_id = $4""",
                reward, now, total_claimed, user_id
            )

            return {'success': True, 'reward': reward, 'total_claimed': total_claimed}

async def claim_weekly(user_id: int) -> dict:
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            await ensure_user_exists(user_id, conn=conn)
            # FOR UPDATE locks the row so concurrent claims queue up
            user = await conn.fetchrow(
                "SELECT last_weekly, total_weekly_claimed FROM users WHERE user_id = $1 FOR UPDATE",
                user_id
            )
            if not user:
                return {'success': False, 'error': 'User not found'}

            now = datetime.now()
            last_weekly = user['last_weekly']

            if last_weekly and (now - last_weekly).total_seconds() < 604800:
                remaining = 604800 - (now - last_weekly).total_seconds()
                days = int(remaining // 86400)
                hours = int((remaining % 86400) // 3600)
                return {'success': False, 'error': f'Already claimed! Next claim in {days}d {hours}h'}

            reward = 5000
            total_claimed = (user['total_weekly_claimed'] or 0) + 1

            await conn.execute(
                """UPDATE users
                   SET balance = balance + $1, last_weekly = $2, total_weekly_claimed = $3
                   WHERE user_id = $4""",
                reward, now, total_claimed, user_id
            )

            return {'success': True, 'reward': reward, 'total_claimed': total_claimed}

# ============================================
# SKIN UPGRADE
# ============================================

async def skin_upgrade(user_id: int, item_id: int) -> dict:
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            await ensure_user_exists(user_id, conn=conn)
            
            item = await conn.fetchrow(
                "SELECT * FROM inventory WHERE id = $1 AND user_id = $2 AND status = 'kept' FOR UPDATE",
                item_id, user_id
            )
            if not item:
                return {'success': False, 'error': 'Item not found in inventory'}

            rarity_order = ['Blue', 'Purple', 'Pink', 'Red', 'Gold']
            if item['rarity'] == 'Gold':
                return {'success': False, 'error': 'Gold items cannot be upgraded! Use gold trade instead.'}

            current_rarity = item['rarity']
            current_index = rarity_order.index(current_rarity)
            next_rarity = rarity_order[current_index + 1] if current_index < len(rarity_order) - 1 else None

            if not next_rarity:
                return {'success': False, 'error': 'Item cannot be upgraded further'}

            chances = {'Blue': 0.8, 'Purple': 0.6, 'Pink': 0.4, 'Red': 0.25}
            success_chance = chances.get(current_rarity, 0.5)
            success = secure_random() < success_chance

            upgrade_cost = {'Blue': 10, 'Purple': 50, 'Pink': 200, 'Red': 1000}.get(current_rarity, 10)

            if not await deduct_balance(user_id, upgrade_cost, conn):
                return {'success': False, 'error': f'Insufficient balance. Upgrade costs ${upgrade_cost}'}

            await conn.execute("DELETE FROM inventory WHERE id = $1", item_id)
            
            if success:
                possible_items = []
                for case in CASES.values():
                    for case_item in case['items']:
                        if case_item['rarity'] == next_rarity:
                            possible_items.append(case_item)
                
                new_item_template = secure_choice(possible_items) if possible_items else {
                    'name': f'Mystery {next_rarity} Item',
                    'rarity': next_rarity,
                    'condition': 'Field-Tested',
                    'tier': None
                }
                
                is_stattrak = secure_random() < 0.1
                float_value = generate_skin_float()
                condition_from_float = get_skin_condition(float_value)
                base_value = calculate_item_value(next_rarity, new_item_template.get('condition', 'Field-Tested'), 
                                                  new_item_template.get('tier'), is_stattrak)
                float_multiplier = {
                    "Factory New": 2.0, "Minimal Wear": 1.5, "Field-Tested": 1.0,
                    "Well-Worn": 0.75, "Battle-Scarred": 0.5
                }.get(condition_from_float, 1.0)
                value = round(base_value * float_multiplier, 2)
                name = f"{'StatTrak™ ' if is_stattrak else ''}{new_item_template['name']}"
                
                await conn.execute(
                    """INSERT INTO inventory 
                       (user_id, item_name, item_type, rarity, price, condition, is_stattrak, status, float_value) 
                       VALUES ($1, $2, 'weapon', $3, $4, $5, $6, 'kept', $7)""",
                    user_id, name, next_rarity, value, condition_from_float, is_stattrak, float_value
                )
                
                await conn.execute(
                    """INSERT INTO skin_upgrades 
                       (user_id, item_id, input_rarity, output_rarity, success) 
                       VALUES ($1, $2, $3, $4, true)""",
                    user_id, item_id, current_rarity, next_rarity
                )
                
                return {
                    'success': True,
                    'upgraded': True,
                    'new_rarity': next_rarity,
                    'new_item_name': name,
                    'new_price': value,
                    'old_rarity': current_rarity,
                    'old_item_name': item['item_name']
                }
            else:
                await conn.execute(
                    """INSERT INTO skin_upgrades 
                       (user_id, item_id, input_rarity, output_rarity, success) 
                       VALUES ($1, $2, $3, $4, false)""",
                    user_id, item_id, current_rarity, next_rarity
                )
                
                return {
                    'success': True,
                    'upgraded': False,
                    'old_item_name': item['item_name'],
                    'old_rarity': current_rarity,
                    'cost': upgrade_cost
                }


# ============================================
# RUN BOT
# ============================================

if __name__ == "__main__":
    if not TOKEN:
        logger.error("❌ DISCORD_BOT_TOKEN not found!")
        exit(1)
    bot.run(TOKEN)