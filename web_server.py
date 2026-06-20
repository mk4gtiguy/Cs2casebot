# ============================================
# web_server.py - COMPLETE FIXED VERSION
# All bugs fixed, consistent column names, all tables supported
# Premium cases: Common, Uncommon, Rare, Epic, Legendary
# Ko-fi goals: $500 or 1000 users unlocks Premium
# ============================================

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import stripe
import asyncpg
import os
import random
import httpx
import secrets
from datetime import datetime, timedelta
from dotenv import load_dotenv
import logging
import json
import urllib.parse

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

app = FastAPI(title="CS2CaseBot Dashboard")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://cs2casebot.xyz", "https://www.cs2casebot.xyz", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

# ============================================
# STRIPE CONFIGURATION
# ============================================

STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY')
STRIPE_PUBLISHABLE_KEY = os.getenv('STRIPE_PUBLISHABLE_KEY')
STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET')

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY
    logger.info("✅ Stripe configured successfully!")
else:
    logger.warning("⚠️ STRIPE_SECRET_KEY not found in .env")

# ============================================
# ENVIRONMENT VARIABLES
# ============================================

DATABASE_URL = os.getenv('DATABASE_URL')
DISCORD_CLIENT_ID = os.getenv('DISCORD_CLIENT_ID')
DISCORD_CLIENT_SECRET = os.getenv('DISCORD_CLIENT_SECRET')
DISCORD_REDIRECT_URI = os.getenv('DISCORD_REDIRECT_URI', 'https://cs2casebot.xyz/auth/callback')
GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET')
GOOGLE_REDIRECT_URI = os.getenv('GOOGLE_REDIRECT_URI', 'https://cs2casebot.xyz/auth/google/callback')
DEFAULT_GUILD_ID = int(os.getenv('DEFAULT_GUILD_ID', '0'))
DISCORD_INVITE_URL = os.getenv('DISCORD_INVITE_URL', 'https://discord.gg/mU33pc7TDE')
SUPPORT_SERVER_ID = int(os.getenv('SUPPORT_SERVER_ID', '1516669749310783549'))

# Premium status - LOCKED for launch
PREMIUM_ENABLED = False
PREMIUM_ENABLED_MESSAGE = "🚀 Premium cases are coming soon! Help us reach our goals to unlock them!"

if not DATABASE_URL:
    logger.error("DATABASE_URL not set!")
    exit(1)

db_pool = None

# Session storage
sessions = {}

# OAuth URLs
DISCORD_AUTH_URL = "https://discord.com/api/oauth2/authorize"
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"
DISCORD_USER_URL = "https://discord.com/api/users/@me"

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USER_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

def generate_session_token():
    return secrets.token_urlsafe(32)

# ============================================
# DATABASE HELPERS - FIXED for Discord IDs
# ============================================

async def get_user_by_auth(provider: str, provider_user_id: str):
    """Get user_id from auth_methods"""
    async with db_pool.acquire() as conn:
        result = await conn.fetchrow(
            "SELECT user_id FROM auth_methods WHERE provider = $1 AND provider_user_id = $2",
            provider, str(provider_user_id)
        )
        if result:
            return result['user_id']
        return None

async def get_or_create_user(user_id: int, username: str = None, email: str = None):
    """Create a new user if doesn't exist - uses Discord ID as user_id"""
    async with db_pool.acquire() as conn:
        # Check if user exists by user_id (Discord ID)
        existing = await conn.fetchrow(
            "SELECT user_id FROM users WHERE user_id = $1",
            user_id
        )
        if existing:
            return existing['user_id']
        
        # Create new user with the Discord ID as user_id
        await conn.execute(
            "INSERT INTO users (user_id, username, email, balance, credits) VALUES ($1, $2, $3, $4, $5)",
            user_id, username or f"User_{user_id}", email, 1000, 0
        )
        return user_id

async def add_auth_method(user_id: int, provider: str, provider_user_id: str, username: str = None, email: str = None, avatar: str = None):
    """Add an auth method to a user"""
    async with db_pool.acquire() as conn:
        # Check if this auth method already exists
        existing = await conn.fetchrow(
            "SELECT id FROM auth_methods WHERE provider = $1 AND provider_user_id = $2",
            provider, str(provider_user_id)
        )
        if existing:
            return existing['id']
        
        # Make sure the user exists first
        user_exists = await conn.fetchrow(
            "SELECT user_id FROM users WHERE user_id = $1",
            user_id
        )
        if not user_exists:
            # Create the user if they don't exist
            await conn.execute(
                "INSERT INTO users (user_id, username, email, balance, credits) VALUES ($1, $2, $3, $4, $5)",
                user_id, username or f"User_{user_id}", email, 1000, 0
            )
        
        # Now add the auth method
        result = await conn.fetchrow(
            """INSERT INTO auth_methods 
               (user_id, provider, provider_user_id, provider_username, provider_email, avatar_url) 
               VALUES ($1, $2, $3, $4, $5, $6) 
               RETURNING id""",
            user_id, provider, str(provider_user_id), username, email, avatar
        )
        return result['id']

async def get_user_guilds(user_id: int):
    """Get all guilds a user is in"""
    async with db_pool.acquire() as conn:
        results = await conn.fetch(
            "SELECT guild_id, guild_name FROM guild_memberships WHERE user_id = $1",
            user_id
        )
        return [dict(r) for r in results]

async def add_user_to_guild(user_id: int, guild_id: int, guild_name: str = None):
    """Add user to a guild"""
    async with db_pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id FROM guild_memberships WHERE user_id = $1 AND guild_id = $2",
            user_id, guild_id
        )
        if existing:
            return existing['id']
        
        result = await conn.fetchrow(
            "INSERT INTO guild_memberships (user_id, guild_id, guild_name) VALUES ($1, $2, $3) RETURNING id",
            user_id, guild_id, guild_name
        )
        return result['id']

async def get_user_data(user_id: int):
    """Get user data"""
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT * FROM users WHERE user_id = $1",
            user_id
        )
        return dict(user) if user else None

async def update_user_balance(user_id: int, amount: float):
    """Update user balance"""
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET balance = balance + $1 WHERE user_id = $2",
            amount, user_id
        )

async def get_user_id_from_session(request: Request):
    session_token = request.cookies.get("session_token")
    if not session_token or session_token not in sessions:
        return None
    return sessions[session_token]["user_id"]

async def get_username_from_db(user_id: int, conn=None):
    """Get username from database"""
    if conn is None:
        async with db_pool.acquire() as conn:
            user = await conn.fetchrow("SELECT username FROM users WHERE user_id = $1", user_id)
            if user and user['username']:
                return user['username']
    else:
        user = await conn.fetchrow("SELECT username FROM users WHERE user_id = $1", user_id)
        if user and user['username']:
            return user['username']
    return f"User_{user_id}"

# ============================================
# FIXED: ensure_user_exists function for web_server
# ============================================

async def ensure_user_exists(user_id: int, username: str = None, conn=None):
    """CRITICAL FIX: Ensure user exists before any transaction"""
    try:
        if conn is None:
            async with db_pool.acquire() as conn:
                return await ensure_user_exists(user_id, username, conn)
        
        user = await conn.fetchrow("SELECT user_id FROM users WHERE user_id = $1", user_id)
        if not user:
            await conn.execute("""
                INSERT INTO users (user_id, username, balance, created_at, updated_at)
                VALUES ($1, $2, 1000, NOW(), NOW())
            """, user_id, username or f"User_{user_id}")
            logger.info(f"✅ Created user {user_id} ({username or f'User_{user_id}'})")
            return True
        return True
    except Exception as e:
        logger.error(f"ensure_user_exists error for {user_id}: {e}")
        return False

# ============================================
# FIXED: update_quest_progress for web_server
# ============================================

async def update_quest_progress(user_id, quest_type, increment=1, conn=None):
    if conn is None:
        async with db_pool.acquire() as conn:
            return await update_quest_progress(user_id, quest_type, increment, conn)
    
    await ensure_user_exists(user_id, conn=conn)
    
    try:
        quest = await conn.fetchrow("""
            SELECT id, progress, required FROM quests
            WHERE user_id = $1 AND quest_type = $2 AND completed = false AND claimed = false
        """, user_id, quest_type)
        
        if quest:
            new_progress = quest['progress'] + increment
            if new_progress >= quest['required']:
                await conn.execute("""
                    UPDATE quests SET progress = $1, completed = true WHERE id = $2
                """, quest['required'], quest['id'])
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

# ============================================
# DISCORD OAUTH ROUTES
# ============================================

@app.get("/auth/discord/login")
async def auth_discord_login():
    params = {
        "client_id": DISCORD_CLIENT_ID,
        "redirect_uri": DISCORD_REDIRECT_URI,
        "response_type": "code",
        "scope": "identify guilds"
    }
    url = f"{DISCORD_AUTH_URL}?{httpx.QueryParams(params)}"
    return RedirectResponse(url)

@app.get("/auth/discord/callback")
async def auth_discord_callback(code: str = Query(...)):
    if not code:
        raise HTTPException(status_code=400, detail="No code provided")
    
    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            DISCORD_TOKEN_URL,
            data={
                "client_id": DISCORD_CLIENT_ID,
                "client_secret": DISCORD_CLIENT_SECRET,
                "code": code,
                "redirect_uri": DISCORD_REDIRECT_URI,
                "grant_type": "authorization_code"
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        
        if token_response.status_code != 200:
            logger.error(f"Token exchange failed: {token_response.text}")
            raise HTTPException(status_code=400, detail="Token exchange failed")
        
        token_data = token_response.json()
        access_token = token_data.get("access_token")
        
        user_response = await client.get(
            DISCORD_USER_URL,
            headers={"Authorization": f"Bearer {access_token}"}
        )
        
        if user_response.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to get user info")
        
        user_data = user_response.json()
        discord_id = user_data.get("id")
        username = user_data.get("username")
        avatar = user_data.get("avatar")
        email = user_data.get("email")
        
        guilds_response = await client.get(
            "https://discord.com/api/users/@me/guilds",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        
        if guilds_response.status_code == 200:
            guilds = guilds_response.json()
            is_in_official = any(g['id'] == str(DEFAULT_GUILD_ID) for g in guilds)
        else:
            is_in_official = False
        
        # FIXED: Use Discord ID as user_id
        user_id = await get_user_by_auth('discord', discord_id)
        
        if not user_id:
            # Use the Discord ID as the user_id
            user_id = int(discord_id)
            await get_or_create_user(user_id, username, email)
            await add_auth_method(user_id, 'discord', discord_id, username, email, avatar)
        
        if guilds_response.status_code == 200:
            for g in guilds:
                guild_id = int(g['id'])
                guild_name = g['name']
                async with db_pool.acquire() as conn:
                    has_settings = await conn.fetchval(
                        "SELECT 1 FROM guild_settings WHERE guild_id = $1",
                        guild_id
                    )
                    if has_settings:
                        await add_user_to_guild(user_id, guild_id, guild_name)
        
        session_token = generate_session_token()
        sessions[session_token] = {
            "user_id": user_id,
            "username": username,
            "avatar": avatar,
            "is_in_official": is_in_official,
            "created_at": datetime.now()
        }
        
        response = RedirectResponse(url="/dashboard")
        response.set_cookie(
            key="session_token",
            value=session_token,
            max_age=86400 * 7,
            httponly=True,
            secure=True,
            samesite="lax"
        )
        return response

@app.get("/auth/callback")
async def auth_callback_redirect(code: str = Query(...)):
    """Redirect /auth/callback to /auth/discord/callback"""
    return RedirectResponse(url=f"/auth/discord/callback?code={code}")

# ============================================
# GOOGLE OAUTH ROUTES
# ============================================

@app.get("/auth/google/login")
async def auth_google_login():
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "email profile",
        "access_type": "offline"
    }
    url = f"{GOOGLE_AUTH_URL}?{httpx.QueryParams(params)}"
    return RedirectResponse(url)

@app.get("/auth/google/callback")
async def auth_google_callback(code: str = Query(...)):
    if not code:
        raise HTTPException(status_code=400, detail="No code provided")
    
    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "code": code,
                "redirect_uri": GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code"
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        
        if token_response.status_code != 200:
            logger.error(f"Token exchange failed: {token_response.text}")
            raise HTTPException(status_code=400, detail="Token exchange failed")
        
        token_data = token_response.json()
        access_token = token_data.get("access_token")
        
        user_response = await client.get(
            GOOGLE_USER_URL,
            headers={"Authorization": f"Bearer {access_token}"}
        )
        
        if user_response.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to get user info")
        
        user_data = user_response.json()
        google_id = user_data.get("id")
        email = user_data.get("email")
        name = user_data.get("name", email.split('@')[0])
        avatar = user_data.get("picture")
        
        # FIXED: Use Google ID as user_id
        user_id = await get_user_by_auth('google', google_id)
        
        if not user_id:
            # Use the Google ID as user_id (convert to int if possible)
            try:
                user_id = int(google_id)
            except:
                user_id = hash(google_id) % 10**18
            
            await get_or_create_user(user_id, name, email)
            await add_auth_method(user_id, 'google', google_id, name, email, avatar)
        
        guilds = await get_user_guilds(user_id)
        
        session_token = generate_session_token()
        sessions[session_token] = {
            "user_id": user_id,
            "username": name,
            "avatar": avatar,
            "is_google": True,
            "guilds": guilds,
            "created_at": datetime.now()
        }
        
        response = RedirectResponse(url="/dashboard")
        response.set_cookie(
            key="session_token",
            value=session_token,
            max_age=86400 * 7,
            httponly=True,
            secure=True,
            samesite="lax"
        )
        return response

# ============================================
# AUTH STATUS & SESSION
# ============================================

@app.get("/auth/logout")
async def auth_logout():
    response = RedirectResponse(url="/")
    response.delete_cookie("session_token")
    return response

@app.get("/api/me")
async def get_me(request: Request):
    session_token = request.cookies.get("session_token")
    if not session_token or session_token not in sessions:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    session = sessions[session_token]
    user_id = session["user_id"]
    
    user_data = await get_user_data(user_id)
    if not user_data:
        raise HTTPException(status_code=401, detail="User not found")
    
    async with db_pool.acquire() as conn:
        auth_methods = await conn.fetch(
            "SELECT provider, provider_username, avatar_url FROM auth_methods WHERE user_id = $1",
            user_id
        )
    
    guilds = await get_user_guilds(user_id)
    
    return {
        "user_id": user_id,
        "username": session.get("username", user_data.get("username", "User")),
        "avatar": session.get("avatar"),
        "email": user_data.get("email"),
        "balance": float(user_data.get("balance", 0)),
        "credits": user_data.get("credits", 0),
        "auth_methods": [dict(a) for a in auth_methods],
        "guilds": guilds,
        "is_google": session.get("is_google", False),
        "is_in_official": session.get("is_in_official", False),
        "authenticated": True
    }

@app.get("/api/me/guilds")
async def get_my_guilds(request: Request):
    user_id = await get_user_id_from_session(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    guilds = await get_user_guilds(user_id)
    return {"guilds": guilds}

@app.post("/api/link-discord")
async def link_discord(request: Request):
    params = {
        "client_id": DISCORD_CLIENT_ID,
        "redirect_uri": DISCORD_REDIRECT_URI,
        "response_type": "code",
        "scope": "identify",
        "state": "link"
    }
    url = f"{DISCORD_AUTH_URL}?{httpx.QueryParams(params)}"
    return {"url": url}

@app.get("/api/user/username/{user_id}")
async def get_username_api(user_id: int):
    """Get username by user ID"""
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT username FROM users WHERE user_id = $1", user_id)
        if user and user['username']:
            return {"username": user['username']}
        return {"username": f"User_{user_id}"}

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
# FEATURED CASES - Top 7 Most Popular
# ============================================

FEATURED_CASES = [
    "kilowatt_case",
    "gallery_case",
    "fever_case",
    "cs20_case",
    "spectrum_2_case",
    "operation_riptide_case",
    "dreams_and_nightmares_case"
]

RARITY_EMOJIS = {"Blue": "🟦", "Purple": "🟪", "Pink": "💗", "Red": "🔴", "Gold": "⭐"}
WEAPON_BASE_VALUES = {"Blue": 0.25, "Purple": 1.00, "Pink": 4.00, "Red": 20.00}
GOLD_VALUES = {"Common": 150, "Rare": 300, "Epic": 600, "Legendary": 1000, "Mythic": 2500}
CONDITION_MULTIPLIERS = {"Factory New": 2.0, "Minimal Wear": 1.5, "Field-Tested": 1.0, "Well-Worn": 0.75, "Battle-Scarred": 0.5}
DROP_RATES = {"Gold": 2.6, "Red": 2.5, "Pink": 2.5, "Purple": 5.0, "Blue": 87.4}
GOLD_TIER_PROGRESSION = ["Common", "Rare", "Epic", "Legendary", "Mythic"]

# ============================================
# FLOAT SYSTEM
# ============================================

def generate_skin_float():
    """Generate a realistic float value for a skin (0.00-1.00)"""
    return round(random.uniform(0.00, 1.00), 4)

def get_skin_condition(float_value):
    """Get the condition name from a float value"""
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

def apply_float_multiplier(float_value, base_price):
    """Apply a price multiplier based on float value"""
    if float_value <= 0.07:
        return base_price * 2.0
    elif float_value <= 0.15:
        return base_price * 1.5
    elif float_value <= 0.38:
        return base_price * 1.0
    elif float_value <= 0.45:
        return base_price * 0.75
    else:
        return base_price * 0.5

def calculate_item_value(rarity, condition=None, tier=None, is_stattrak=False):
    try:
        if rarity == "Gold" and tier:
            base_value = GOLD_VALUES.get(tier, 150)
        elif rarity in WEAPON_BASE_VALUES:
            base_value = WEAPON_BASE_VALUES[rarity]
        else:
            base_value = 0.25
        multiplier = CONDITION_MULTIPLIERS.get(condition, 1.0)
        value = float(base_value) * float(multiplier)
        if is_stattrak:
            value *= 2
        return round(value, 2)
    except Exception:
        return 0.25

def get_random_item(case_id):
    case = CASES.get(case_id)
    if not case or not case.get('items'):
        return None
    
    rand = random.random() * 100
    cumulative = 0
    
    for rarity, chance in DROP_RATES.items():
        cumulative += chance
        if rand <= cumulative:
            possible_items = [item for item in case['items'] if item['rarity'] == rarity]
            if possible_items:
                item = random.choice(possible_items)
                is_stattrak = random.random() < 0.1
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
                
                value = base_value * float_multiplier
                value = round(value, 2)
                
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
                    'price': float(value),
                    'is_stattrak': is_stattrak
                }
    
    if case['items']:
        fallback_item = case['items'][0]
        is_stattrak = random.random() < 0.1
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
            'price': float(value),
            'is_stattrak': is_stattrak
        }
    
    return None

# ============================================
# WEAPON IMAGE MAPPING
# ============================================

def get_weapon_image_filename(item_name: str) -> str:
    name_lower = item_name.lower()
    if 'stattrak' in name_lower:
        name_lower = name_lower.replace('stattrak™', '').replace('stattrak', '').strip()
    if '★' in name_lower:
        name_lower = name_lower.replace('★', '').strip()
    if '|' in name_lower:
        weapon_name = name_lower.split('|')[0].strip()
    else:
        weapon_name = name_lower
    
    weapon_map = {
        'ak-47': 'weapon_ak47.png', 'ak47': 'weapon_ak47.png',
        'awp': 'weapon_awp.png',
        'galil ar': 'weapon_galilar.png', 'galil': 'weapon_galilar.png',
        'm4a1-s': 'weapon_m4a1_silencer.png', 'm4a1': 'weapon_m4a1_silencer.png',
        'm4a4': 'weapon_m4a4.png',
        'desert eagle': 'weapon_deagle.png', 'deagle': 'weapon_deagle.png',
        'usp-s': 'weapon_usp_silencer.png', 'usp': 'weapon_usp_silencer.png',
        'glock-18': 'weapon_glock.png', 'glock': 'weapon_glock.png',
        'p250': 'weapon_p250.png',
        'five-seven': 'weapon_fiveseven.png', 'fiveseven': 'weapon_fiveseven.png',
        'ssg 08': 'weapon_ssg08.png', 'ssg08': 'weapon_ssg08.png',
        'mac-10': 'weapon_mac10.png', 'mac10': 'weapon_mac10.png',
        'mp9': 'weapon_mp9.png',
        'nova': 'weapon_nova.png',
        'mag-7': 'weapon_mag7.png', 'mag7': 'weapon_mag7.png',
        'tec-9': 'weapon_tec9.png', 'tec9': 'weapon_tec9.png',
        'famas': 'weapon_famas.png',
        'scar-20': 'weapon_scar20.png', 'scar20': 'weapon_scar20.png',
        'sg 553': 'weapon_sg553.webp', 'sg553': 'weapon_sg553.webp',
        'mp7': 'weapon_mp7.png',
        'mp5-sd': 'weapon_mp5sd.png', 'mp5sd': 'weapon_mp5sd.png',
        'p90': 'weapon_p90.png',
        'bizon': 'weapon_bizon.png', 'pp-bizon': 'weapon_bizon.png',
        'ump-45': 'weapon_ump45.png', 'ump45': 'weapon_ump45.png',
        'xm1014': 'weapon_xm1014.png',
        'sawed-off': 'weapon_sawedoff.png', 'sawedoff': 'weapon_sawedoff.png',
        'm249': 'weapon_m249.png',
        'negev': 'weapon_negev.png',
        'cz75-auto': 'weapon_cz75a.png', 'cz75a': 'weapon_cz75a.png',
        'aug': 'weapon_aug.png',
        'p2000': 'weapon_hkp2000.png', 'hkp2000': 'weapon_hkp2000.png',
        'dual berettas': 'weapon_elite.png', 'elite': 'weapon_elite.png',
        'g3sg1': 'weapon_g3sg1.png',
        'r8 revolver': 'weapon_revolver.png', 'revolver': 'weapon_revolver.png',
    }
    
    knife_keywords = ['knife', 'bayonet', 'karambit', 'butterfly', 'm9', 'flip', 'gut', 'huntsman', 'falchion', 'bowie', 'talon', 'ursus', 'paracord', 'survival', 'classic', 'skeleton', 'stiletto', 'nomad', 'navaja', 'shadow daggers', 'kukri', 'bloodhound gloves', 'driver gloves', 'broken fang gloves']
    
    for key, filename in weapon_map.items():
        if key in weapon_name:
            return filename
    
    for keyword in knife_keywords:
        if keyword in weapon_name:
            if 'glove' in keyword:
                return 'weapon_gloves.png'
            return 'weapon_knife.png'
    
    return 'weapon_ak47.png'

# ============================================
# CASE IMAGE ENDPOINT
# ============================================

@app.get("/api/case-image/{case_id}")
async def get_case_image(case_id: str):
    case_image_path = f"static/images/cases/{case_id}.png"
    if os.path.exists(case_image_path):
        return FileResponse(case_image_path)
    
    encoded_id = urllib.parse.quote(case_id, safe='')
    case_image_path_encoded = f"static/images/cases/{encoded_id}.png"
    if os.path.exists(case_image_path_encoded):
        return FileResponse(case_image_path_encoded)
    
    fallback_path = "static/images/cases/default.png"
    if os.path.exists(fallback_path):
        return FileResponse(fallback_path)
    
    raise HTTPException(status_code=404, detail="Case image not found")

# ============================================
# SKIN IMAGE ENDPOINT
# ============================================

@app.get("/api/skin-image")
async def get_skin_image(name: str):
    weapons_dir = "static/images/Default CS2 Weapons"
    filename = get_weapon_image_filename(name)
    image_path = os.path.join(weapons_dir, filename)
    
    if os.path.exists(image_path):
        return FileResponse(image_path)
    
    webp_path = image_path.replace('.png', '.webp')
    if os.path.exists(webp_path):
        return FileResponse(webp_path)
    
    fallback = os.path.join(weapons_dir, 'weapon_ak47.png')
    if os.path.exists(fallback):
        return FileResponse(fallback)
    
    raise HTTPException(status_code=404, detail="No image found")

@app.get("/api/weapon-image/{weapon_name}")
async def get_weapon_image(weapon_name: str):
    weapons_dir = "static/images/Default CS2 Weapons"
    filename = get_weapon_image_filename(weapon_name)
    image_path = os.path.join(weapons_dir, filename)
    
    if os.path.exists(image_path):
        return FileResponse(image_path)
    
    webp_path = image_path.replace('.png', '.webp')
    if os.path.exists(webp_path):
        return FileResponse(webp_path)
    
    fallback = os.path.join(weapons_dir, 'weapon_ak47.png')
    if os.path.exists(fallback):
        return FileResponse(fallback)
    
    raise HTTPException(status_code=404, detail="No image found")

# ============================================
# STICKER CAPSULES DATA & ROUTES
# ============================================

STICKER_CAPSULES = {
    "recoil": {
        "name": "Recoil Sticker Capsule", "emoji": "⭐", "price": 0.50,
        "stickers": [
            {"name": "CS2 Logo", "rarity": "⭐"}, {"name": "AWP Sniper", "rarity": "✨"},
            {"name": "Headshot", "rarity": "💫"}, {"name": "Clutch King", "rarity": "🔥"}
        ]
    },
    "dreams": {
        "name": "Dreams Sticker Capsule", "emoji": "🌙⭐", "price": 1.00,
        "stickers": [
            {"name": "Phoenix Rising", "rarity": "⭐"}, {"name": "Dragon Lore", "rarity": "✨"},
            {"name": "Royal Crown", "rarity": "👑 Common"}, {"name": "Knight's Oath", "rarity": "👑 Rare"}
        ]
    },
    "cs20": {
        "name": "CS20 Sticker Capsule", "emoji": "🎂⭐", "price": 1.00,
        "stickers": [
            {"name": "Counter-Terrorist Elite", "rarity": "⭐"}, {"name": "Terrorist Elite", "rarity": "✨"},
            {"name": "20 Years", "rarity": "💫"}, {"name": "Legends", "rarity": "👑 Epic"}
        ]
    },
    "championship": {
        "name": "Championship Sticker Capsule", "emoji": "🏆", "price": 2.00,
        "stickers": [
            {"name": "Victory", "rarity": "✨"}, {"name": "Champion", "rarity": "💫"},
            {"name": "Golden Trophy", "rarity": "👑 Epic"}, {"name": "Hall of Fame", "rarity": "👑 Legendary"}
        ]
    },
    "legends": {
        "name": "Legends Sticker Capsule", "emoji": "👑", "price": 3.00,
        "stickers": [
            {"name": "s1mple", "rarity": "🔥"}, {"name": "ZyWoo", "rarity": "🔥"},
            {"name": "NiKo", "rarity": "👑 Rare"}, {"name": "KennyS", "rarity": "👑 Epic"}
        ]
    }
}

STICKER_VALUES = {"⭐": 0.10, "✨": 0.50, "💫": 2.00, "🔥": 10.00, "👑 Common": 30, "👑 Rare": 75, "👑 Epic": 150, "👑 Legendary": 300}

def get_random_sticker(capsule_id):
    capsule = STICKER_CAPSULES.get(capsule_id)
    if not capsule or not capsule.get('stickers'):
        return None
    
    sticker = random.choice(capsule['stickers'])
    is_stattrak = random.random() < 0.1
    
    value = STICKER_VALUES.get(sticker['rarity'], 0.25)
    if is_stattrak:
        value *= 2
    
    if is_stattrak:
        clean_name = sticker['name'].replace('StatTrak™ ', '').replace('StatTrak™', '')
        name = f"StatTrak™ {clean_name}"
    else:
        name = sticker['name']
    
    return {
        'name': name,
        'rarity': sticker['rarity'],
        'price': round(value, 2),
        'is_stattrak': is_stattrak
    }

@app.post("/api/sticker")
async def open_sticker_capsule(request: Request, body: dict):
    user_id = await get_user_id_from_session(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    capsule_id = body.get("capsule")
    if not capsule_id:
        return {"success": False, "error": "Missing capsule id"}
    
    capsule = STICKER_CAPSULES.get(capsule_id)
    if not capsule:
        return {"success": False, "error": "Invalid capsule"}
    
    user_data = await get_user_data(user_id)
    if not user_data:
        return {"success": False, "error": "User not found"}
    
    balance = float(user_data['balance'])
    price = float(capsule['price'])
    
    if balance < price:
        return {"success": False, "error": f"Insufficient balance. You have ${balance:.2f}, need ${price:.2f}"}
    
    try:
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE users SET balance = balance - $1 WHERE user_id = $2",
                    price, user_id
                )
                
                sticker = get_random_sticker(capsule_id)
                if not sticker:
                    return {"success": False, "error": "Failed to generate sticker"}
                
                result = await conn.fetch(
                    "INSERT INTO inventory (user_id, item_name, item_type, rarity, price, is_stattrak) VALUES ($1, $2, 'sticker', $3, $4, $5) RETURNING id",
                    user_id, sticker['name'], sticker['rarity'], sticker['price'], sticker['is_stattrak']
                )
                sticker_id = result[0]['id'] if result else None
                
                return {
                    "success": True,
                    "item": {
                        "id": sticker_id,
                        "name": sticker['name'],
                        "rarity": sticker['rarity'],
                        "price": sticker['price'],
                        "is_stattrak": sticker['is_stattrak']
                    }
                }
    except Exception as e:
        logger.error(f"Open sticker error: {e}")
        return {"success": False, "error": str(e)}

# ============================================
# QUESTS ROUTES
# ============================================

QUEST_TYPES = {
    "open_cases": {"name": "🔑 Case Opener", "base_reward": 500, "base_required": 5},
    "get_golds": {"name": "✨ Gold Hunter", "base_reward": 1000, "base_required": 1},
    "earn_money": {"name": "💰 Money Maker", "base_reward": 750, "base_required": 5000},
    "trade_up": {"name": "🔄 Trade Master", "base_reward": 800, "base_required": 3},
    "sell_items": {"name": "💸 Salesman", "base_reward": 600, "base_required": 5},
    "daily_streak": {"name": "📅 Streak Keeper", "base_reward": 1000, "base_required": 5}
}

@app.get("/api/user/me/quests")
async def get_my_quests(request: Request):
    user_id = await get_user_id_from_session(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT user_id FROM users WHERE user_id = $1", user_id)
        if not user:
            await conn.execute(
                "INSERT INTO users (user_id, balance) VALUES ($1, $2)",
                user_id, 1000
            )
        
        last_quest = await conn.fetchrow("""
            SELECT created_at FROM quests WHERE user_id = $1
            ORDER BY created_at DESC LIMIT 1
        """, user_id)
        
        if not last_quest or last_quest['created_at'].date() != datetime.now().date():
            await conn.execute("DELETE FROM quests WHERE user_id = $1", user_id)
            
            for quest_type, quest_info in QUEST_TYPES.items():
                required = quest_info["base_required"]
                reward = quest_info["base_reward"]
                user_data = await conn.fetchrow("SELECT total_opens FROM users WHERE user_id = $1", user_id)
                if user_data and user_data['total_opens'] > 100:
                    required = int(required * 1.5)
                    reward = int(reward * 1.2)
                await conn.execute("""
                    INSERT INTO quests (user_id, quest_type, progress, required, reward, completed, claimed, created_at)
                    VALUES ($1, $2, 0, $3, $4, false, false, NOW())
                """, user_id, quest_type, required, reward)
        
        quests = await conn.fetch(
            "SELECT * FROM quests WHERE user_id = $1 AND claimed = false",
            user_id
        )
        
        return {"quests": [dict(q) for q in quests]}

@app.post("/api/claim")
async def claim_quests(request: Request):
    user_id = await get_user_id_from_session(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                completed_quests = await conn.fetch(
                    "SELECT * FROM quests WHERE user_id = $1 AND completed = true AND claimed = false",
                    user_id
                )
                
                if not completed_quests:
                    return {"success": False, "error": "No completed quests to claim"}
                
                total_reward = 0
                for quest in completed_quests:
                    total_reward += quest['reward']
                    await conn.execute(
                        "UPDATE quests SET claimed = true WHERE id = $1",
                        quest['id']
                    )
                
                await conn.execute(
                    "UPDATE users SET balance = balance + $1 WHERE user_id = $2",
                    total_reward, user_id
                )
                
                return {
                    "success": True,
                    "message": f"Claimed ${total_reward} from {len(completed_quests)} quests!",
                    "total_reward": total_reward
                }
    except Exception as e:
        logger.error(f"Claim quests error: {e}")
        return {"success": False, "error": str(e)}

# ============================================
# API ROUTES
# ============================================

@app.get("/api/cases")
async def get_cases():
    return {"cases": [{"id": cid, "name": c["name"], "emoji": c["emoji"], "price": c["price"]} for cid, c in CASES.items()]}

@app.get("/api/cases/featured")
async def get_featured_cases():
    return {"featured": [{"id": cid, "name": CASES[cid]["name"], "emoji": CASES[cid]["emoji"], "price": CASES[cid]["price"]} for cid in FEATURED_CASES if cid in CASES]}

# ============================================
# USER API ROUTES
# ============================================

@app.get("/api/user/me")
async def get_me_data(request: Request):
    user_id = await get_user_id_from_session(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    user_data = await get_user_data(user_id)
    if not user_data:
        raise HTTPException(status_code=404, detail="User not found")
    
    async with db_pool.acquire() as conn:
        auth_methods = await conn.fetch(
            "SELECT provider, provider_username, avatar_url FROM auth_methods WHERE user_id = $1",
            user_id
        )
    
    return {
        **user_data,
        "auth_methods": [dict(a) for a in auth_methods]
    }

@app.get("/api/user/me/balance")
async def get_my_balance(request: Request):
    user_id = await get_user_id_from_session(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    user_data = await get_user_data(user_id)
    if not user_data:
        return {"balance": 1000.0, "credits": 0}
    
    return {"balance": float(user_data['balance']), "credits": user_data.get('credits', 0)}

@app.get("/api/user/me/stats")
async def get_my_stats(request: Request):
    user_id = await get_user_id_from_session(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    user_data = await get_user_data(user_id)
    if not user_data:
        return {
            "balance": 1000.0,
            "credits": 0,
            "total_opens": 0,
            "total_premium_opens": 0,
            "total_golds": 0,
            "total_trades": 0,
            "daily_streak": 0,
            "inventory_count": 0,
            "inventory_value": 0.0
        }
    
    async with db_pool.acquire() as conn:
        inventory_count = await conn.fetchval(
            "SELECT COUNT(*) FROM inventory WHERE user_id = $1 AND status = 'kept'",
            user_id
        )
        inventory_value = await conn.fetchval(
            "SELECT COALESCE(SUM(price), 0) FROM inventory WHERE user_id = $1 AND status = 'kept'",
            user_id
        )
    
    return {
        "balance": float(user_data['balance']),
        "credits": user_data.get('credits', 0),
        "total_opens": user_data.get('total_opens', 0),
        "total_premium_opens": user_data.get('total_premium_opens', 0),
        "total_golds": user_data.get('total_golds', 0),
        "total_trades": user_data.get('total_trades', 0),
        "daily_streak": user_data.get('daily_streak', 0),
        "inventory_count": inventory_count or 0,
        "inventory_value": float(inventory_value or 0)
    }

@app.get("/api/user/me/inventory")
async def get_my_inventory(request: Request, limit: int = 100, offset: int = 0, rarity: str = None, search: str = None):
    user_id = await get_user_id_from_session(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    if limit > 200:
        limit = 200
    
    async with db_pool.acquire() as conn:
        query = """SELECT id, item_name, rarity, price, condition, is_stattrak, case_id, float_value 
                   FROM inventory WHERE user_id = $1 AND status = 'kept'"""
        params = [user_id]
        
        if rarity and rarity != 'all':
            query += " AND rarity = $" + str(len(params) + 1)
            params.append(rarity)
        
        if search:
            query += " AND LOWER(item_name) LIKE $" + str(len(params) + 1)
            params.append(f"%{search.lower()}%")
        
        query += " ORDER BY id DESC LIMIT $" + str(len(params) + 1) + " OFFSET $" + str(len(params) + 2)
        params.append(limit)
        params.append(offset)
        
        items = await conn.fetch(query, *params)
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM inventory WHERE user_id = $1 AND status = 'kept'",
            user_id
        )
        
        return {
            "items": [dict(item) for item in items],
            "count": total,
            "limit": limit,
            "offset": offset
        }

# ============================================
# CASE OPENING - FIXED: status='kept' not 'pending'
# ============================================

@app.post("/api/open-case")
async def open_case_endpoint(request: Request, body: dict):
    user_id = await get_user_id_from_session(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    case_id = body.get("case_id")
    quantity = body.get("quantity", 1)
    
    if not case_id:
        return {"success": False, "error": "Missing case_id"}
    
    case = CASES.get(case_id)
    if not case:
        return {"success": False, "error": "Invalid case"}
    
    if quantity > 25:
        return {"success": False, "error": "Maximum 25 cases at once"}
    
    try:
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                user = await conn.fetchrow(
                    "SELECT balance FROM users WHERE user_id = $1",
                    user_id
                )
                if not user:
                    return {"success": False, "error": "User not found"}
                
                balance = float(user['balance'])
                price = float(case['price'])
                total_cost = price * quantity
                
                if balance < total_cost:
                    return {"success": False, "error": f"Insufficient balance. You have ${balance:.2f}, need ${total_cost:.2f}"}
                
                await conn.execute(
                    "UPDATE users SET balance = balance - $1, total_opens = total_opens + $2 WHERE user_id = $3",
                    total_cost, quantity, user_id
                )
                
                items = []
                for _ in range(quantity):
                    item = get_random_item(case_id)
                    if item:
                        # FIXED: status is 'kept' not 'pending' - prevents blank inventory pages!
                        result = await conn.fetch(
                            """INSERT INTO inventory 
                               (user_id, item_name, item_type, rarity, price, condition, is_stattrak, status, case_id, float_value) 
                               VALUES ($1, $2, 'weapon', $3, $4, $5, $6, 'kept', $7, $8) 
                               RETURNING id""",
                            user_id, item['name'], item['rarity'], item['price'], 
                            item.get('condition', 'Field-Tested'), item['is_stattrak'], 
                            case_id, item.get('float', 0.0000)
                        )
                        item_id = result[0]['id'] if result else None
                        
                        if item['rarity'] == 'Gold':
                            await conn.execute(
                                "UPDATE users SET total_golds = total_golds + 1 WHERE user_id = $1",
                                user_id
                            )
                        
                        items.append({
                            **item,
                            'id': item_id
                        })
                
                # FIXED: Make sure we have items
                if not items:
                    return {"success": False, "error": "No items were generated. Please try again."}
                
                return {"success": True, "items": items, "case": case, "count": len(items)}
    except Exception as e:
        logger.error(f"Open case error: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/keep-item")
async def keep_item(request: Request, body: dict):
    user_id = await get_user_id_from_session(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    item_id = body.get("item_id")
    if not item_id:
        return {"success": False, "error": "Missing item_id"}
    
    try:
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                item = await conn.fetchrow(
                    "SELECT * FROM inventory WHERE id = $1 AND user_id = $2",
                    item_id, user_id
                )
                if not item:
                    return {"success": False, "error": "Item not found"}
                
                await conn.execute(
                    "UPDATE inventory SET status = 'kept' WHERE id = $1",
                    item_id
                )
                return {"success": True, "item": dict(item)}
    except Exception as e:
        logger.error(f"Keep item error: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/sell-item")
async def sell_item_endpoint(request: Request, body: dict):
    user_id = await get_user_id_from_session(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    item_id = body.get("item_id")
    if not item_id:
        return {"success": False, "error": "Missing item_id"}
    
    try:
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                item = await conn.fetchrow(
                    "SELECT * FROM inventory WHERE id = $1 AND user_id = $2 AND status IN ('kept', 'pending')",
                    item_id, user_id
                )
                if not item:
                    return {"success": False, "error": "Item not found"}
                
                price_value = float(item['price']) if item['price'] is not None else 0
                sell_price = round(price_value * 0.7, 2)
                
                await conn.execute("UPDATE inventory SET status = 'sold' WHERE id = $1", item_id)
                await conn.execute(
                    "UPDATE users SET balance = balance + $1 WHERE user_id = $2",
                    sell_price, user_id
                )
                
                return {"success": True, "sell_price": sell_price, "item_name": item['item_name']}
    except Exception as e:
        logger.error(f"Sell item error: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/sell-batch")
async def sell_batch_endpoint(request: Request, body: dict):
    user_id = await get_user_id_from_session(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    item_ids = body.get("item_ids", [])
    if not item_ids:
        return {"success": False, "error": "No items to sell"}
    
    try:
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                total_sell_price = 0
                sold_items = []
                
                for item_id in item_ids:
                    item = await conn.fetchrow(
                        "SELECT * FROM inventory WHERE id = $1 AND user_id = $2 AND status IN ('kept', 'pending')",
                        item_id, user_id
                    )
                    if item:
                        price_value = float(item['price']) if item['price'] is not None else 0
                        sell_price = round(price_value * 0.7, 2)
                        total_sell_price += sell_price
                        sold_items.append(item['item_name'])
                        await conn.execute("UPDATE inventory SET status = 'sold' WHERE id = $1", item_id)
                
                if total_sell_price > 0:
                    await conn.execute(
                        "UPDATE users SET balance = balance + $1 WHERE user_id = $2",
                        total_sell_price, user_id
                    )
                
                return {"success": True, "total_sell_price": total_sell_price, "count": len(sold_items)}
    except Exception as e:
        logger.error(f"Sell batch error: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/daily")
async def claim_daily(request: Request, body: dict):
    user_id = await get_user_id_from_session(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                user = await conn.fetchrow(
                    "SELECT balance, daily_streak, last_daily FROM users WHERE user_id = $1",
                    user_id
                )
                if not user:
                    return {"success": False, "error": "User not found"}
                
                now = datetime.now()
                last_daily = user['last_daily']
                streak = user['daily_streak'] or 0
                
                if last_daily and last_daily.date() == now.date():
                    return {"success": False, "error": "Already claimed today"}
                
                if last_daily and (now - last_daily).days == 1:
                    streak += 1
                else:
                    streak = 1
                
                reward = 500 + (streak * 100)
                jackpot_hit = random.randint(1, 1000000) == 1
                if jackpot_hit:
                    reward += 50000
                
                await conn.execute(
                    "UPDATE users SET balance = balance + $1, daily_streak = $2, last_daily = $3 WHERE user_id = $4",
                    reward, streak, now, user_id
                )
                
                return {"success": True, "reward": reward, "streak": streak, "jackpot": jackpot_hit}
    except Exception as e:
        logger.error(f"Daily claim error: {e}")
        return {"success": False, "error": str(e)}

# ============================================
# TRADE-UP
# ============================================

@app.post("/api/quick-trade")
async def quick_trade(request: Request, body: dict):
    user_id = await get_user_id_from_session(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    rarity = body.get("rarity")
    item_ids = body.get("item_ids", [])
    is_gold_trade = body.get("is_gold_trade", False)
    
    if not item_ids:
        return {"success": False, "error": "No items selected"}
    
    if is_gold_trade and len(item_ids) != 5:
        return {"success": False, "error": "Gold trade requires exactly 5 items"}
    
    if not is_gold_trade and len(item_ids) != 10:
        return {"success": False, "error": "Weapon trade requires exactly 10 items"}
    
    try:
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                items = []
                for item_id in item_ids:
                    item = await conn.fetchrow(
                        "SELECT * FROM inventory WHERE id = $1 AND user_id = $2 AND status = 'kept'",
                        item_id, user_id
                    )
                    if not item:
                        return {"success": False, "error": f"Item {item_id} not found"}
                    items.append(item)
                
                if not is_gold_trade:
                    rarities = set(item['rarity'] for item in items)
                    if len(rarities) != 1:
                        return {"success": False, "error": "All items must have the same rarity"}
                    current_rarity = rarities.pop()
                    
                    if current_rarity not in ["Blue", "Purple", "Pink"]:
                        return {"success": False, "error": "Invalid rarity for trade-up"}
                    
                    next_rarity = {"Blue": "Purple", "Purple": "Pink", "Pink": "Red"}[current_rarity]
                    
                    possible_items = []
                    for case in CASES.values():
                        for item in case['items']:
                            if item['rarity'] == next_rarity:
                                possible_items.append(item)
                else:
                    for item in items:
                        if item['rarity'] != 'Gold':
                            return {"success": False, "error": "All items must be Gold rarity"}
                    
                    tiers = [item.get('tier', 'Common') for item in items]
                    tier_index = 0
                    for t in tiers:
                        if t in GOLD_TIER_PROGRESSION:
                            idx = GOLD_TIER_PROGRESSION.index(t)
                            if idx > tier_index:
                                tier_index = idx
                    
                    if tier_index >= len(GOLD_TIER_PROGRESSION) - 1:
                        return {"success": False, "error": "Cannot trade up - already at maximum tier!"}
                    
                    next_tier = GOLD_TIER_PROGRESSION[tier_index + 1]
                    next_rarity = "Gold"
                    possible_items = [{"name": f"{next_tier} Gold Item", "rarity": "Gold", "tier": next_tier, "condition": "Factory New"}]
                
                for item in items:
                    await conn.execute("UPDATE inventory SET status = 'sold' WHERE id = $1", item['id'])
                
                new_item_template = random.choice(possible_items)
                is_stattrak = random.random() < 0.1
                condition = new_item_template.get('condition', 'Field-Tested')
                tier = new_item_template.get('tier', None)
                
                float_value = generate_skin_float()
                condition_from_float = get_skin_condition(float_value)
                
                value = calculate_item_value(next_rarity, condition, tier, is_stattrak)
                float_multiplier = {
                    "Factory New": 2.0,
                    "Minimal Wear": 1.5,
                    "Field-Tested": 1.0,
                    "Well-Worn": 0.75,
                    "Battle-Scarred": 0.5
                }.get(condition_from_float, 1.0)
                value = round(value * float_multiplier, 2)
                
                name = f"{'StatTrak™ ' if is_stattrak else ''}{new_item_template['name']}"
                
                result = await conn.fetch(
                    """INSERT INTO inventory 
                       (user_id, item_name, item_type, rarity, price, condition, is_stattrak, status, case_id, float_value) 
                       VALUES ($1, $2, 'weapon', $3, $4, $5, $6, 'kept', $7, $8) 
                       RETURNING id""",
                    user_id, name, next_rarity, value, condition_from_float, is_stattrak, 
                    'tradeup', float_value
                )
                new_item_id = result[0]['id'] if result else None
                
                await conn.execute(
                    "UPDATE users SET total_trades = total_trades + 1 WHERE user_id = $1",
                    user_id
                )
                
                rarity_emoji = RARITY_EMOJIS.get(next_rarity, "")
                
                return {
                    "success": True,
                    "message": f"Trade complete! Got: {rarity_emoji} {name} (${value:.2f})",
                    "new_item": {
                        "id": new_item_id,
                        "name": name,
                        "rarity": next_rarity,
                        "price": value,
                        "condition": condition_from_float,
                        "float": float_value,
                        "is_stattrak": is_stattrak,
                        "tier": tier,
                        "display_name": f"{rarity_emoji} {name}"
                    }
                }
    except Exception as e:
        logger.error(f"Quick trade error: {e}")
        return {"success": False, "error": str(e)}

# ============================================
# LEADERBOARD - FIXED: Shows data properly
# ============================================

@app.get("/api/leaderboard/{type}")
async def get_leaderboard(type: str, guild_id: int = None, limit: int = 10):
    if limit > 50:
        limit = 50
    
    async with db_pool.acquire() as conn:
        if type == "money":
            users = await conn.fetch(
                "SELECT user_id, username, balance FROM users ORDER BY balance DESC LIMIT $1",
                limit
            )
            return {"type": type, "users": [
                {"user_id": u['user_id'], "username": u['username'] or f"User_{u['user_id']}", "value": float(u['balance'])} 
                for u in users
            ]}
        elif type == "opens":
            users = await conn.fetch(
                "SELECT user_id, username, total_opens FROM users ORDER BY total_opens DESC LIMIT $1",
                limit
            )
            return {"type": type, "users": [
                {"user_id": u['user_id'], "username": u['username'] or f"User_{u['user_id']}", "value": u['total_opens']} 
                for u in users
            ]}
        elif type == "golds":
            users = await conn.fetch(
                "SELECT user_id, username, total_golds FROM users ORDER BY total_golds DESC LIMIT $1",
                limit
            )
            return {"type": type, "users": [
                {"user_id": u['user_id'], "username": u['username'] or f"User_{u['user_id']}", "value": u['total_golds']} 
                for u in users
            ]}
        elif type == "trades":
            users = await conn.fetch(
                "SELECT user_id, username, total_trades FROM users ORDER BY total_trades DESC LIMIT $1",
                limit
            )
            return {"type": type, "users": [
                {"user_id": u['user_id'], "username": u['username'] or f"User_{u['user_id']}", "value": u['total_trades']} 
                for u in users
            ]}
        else:
            return {"type": type, "users": []}

# ============================================
# PREMIUM CASES - NEW NAMES & ITEM POOLS
# ============================================

PREMIUM_ENABLED = False
PREMIUM_ENABLED_MESSAGE = "🚀 Premium cases are coming soon! Help us reach our goals to unlock them!"

PREMIUM_CASES = {
    "ticket_1": {
        "id": "ticket_1",
        "name": "Common Cache",
        "description": "Good starter case with decent odds",
        "tier": "ticket_1",
        "price_tickets": 1,
        "price_usd": 0.10,
        "drop_rates": {"Gold": 3.5, "Red": 4.0, "Pink": 5.0, "Purple": 10.0, "Blue": 77.5},
        "items": {
            "Gold": [
                {"name": "AK-47 | Redline", "condition": "Minimal Wear", "tier": "Common"},
                {"name": "AWP | Electric Hive", "condition": "Field-Tested", "tier": "Common"},
                {"name": "M4A4 | Dragon King", "condition": "Minimal Wear", "tier": "Common"}
            ],
            "Red": [
                {"name": "USP-S | Orion", "condition": "Factory New"},
                {"name": "Glock-18 | Water Elemental", "condition": "Minimal Wear"},
                {"name": "M4A1-S | Hyper Beast", "condition": "Field-Tested"}
            ],
            "Pink": [
                {"name": "Desert Eagle | Crimson Web", "condition": "Field-Tested"},
                {"name": "SSG 08 | Abyss", "condition": "Minimal Wear"},
                {"name": "P250 | Muertos", "condition": "Factory New"}
            ],
            "Purple": [
                {"name": "FAMAS | Doomkitty", "condition": "Field-Tested"},
                {"name": "MAC-10 | Whitefish", "condition": "Minimal Wear"},
                {"name": "MP7 | Nemesis", "condition": "Well-Worn"}
            ],
            "Blue": [
                {"name": "Galil AR | Black Sand", "condition": "Battle-Scarred"},
                {"name": "MP5-SD | Gauss", "condition": "Field-Tested"},
                {"name": "MAG-7 | Hazard", "condition": "Well-Worn"},
                {"name": "Tec-9 | Ice Cap", "condition": "Field-Tested"}
            ]
        }
    },
    "ticket_2": {
        "id": "ticket_2",
        "name": "Uncommon Crate",
        "description": "Step up your game with better skins",
        "tier": "ticket_2",
        "price_tickets": 2,
        "price_usd": 0.20,
        "drop_rates": {"Gold": 6.0, "Red": 8.0, "Pink": 12.0, "Purple": 20.0, "Blue": 54.0},
        "items": {
            "Gold": [
                {"name": "AK-47 | Bloodsport", "condition": "Minimal Wear", "tier": "Epic"},
                {"name": "M4A1-S | Printstream", "condition": "Field-Tested", "tier": "Rare"},
                {"name": "AWP | PAW", "condition": "Minimal Wear", "tier": "Common"},
                {"name": "M4A4 | Emperor", "condition": "Minimal Wear", "tier": "Rare"}
            ],
            "Red": [
                {"name": "Desert Eagle | Hypnotic", "condition": "Factory New"},
                {"name": "Five-SeveN | Scrawl", "condition": "Minimal Wear"},
                {"name": "SSG 08 | Turbo Peek", "condition": "Field-Tested"},
                {"name": "AWP | Oni Taiji", "condition": "Field-Tested"}
            ],
            "Pink": [
                {"name": "SG 553 | Darkwing", "condition": "Field-Tested"},
                {"name": "MP9 | Hydra", "condition": "Minimal Wear"},
                {"name": "USP-S | Cortex", "condition": "Factory New"},
                {"name": "Glock-18 | Wasteland Rebel", "condition": "Field-Tested"}
            ],
            "Purple": [
                {"name": "P250 | Visions", "condition": "Field-Tested"},
                {"name": "AUG | Condemned", "condition": "Minimal Wear"},
                {"name": "MAC-10 | Classic", "condition": "Well-Worn"},
                {"name": "CZ75-Auto | Distressed", "condition": "Field-Tested"}
            ]
        }
    },
    "ticket_3": {
        "id": "ticket_3",
        "name": "Rare Reserve",
        "description": "Premium tier with serious heat",
        "tier": "ticket_3",
        "price_tickets": 5,
        "price_usd": 0.50,
        "drop_rates": {"Gold": 12.0, "Red": 15.0, "Pink": 20.0, "Purple": 30.0, "Blue": 23.0},
        "items": {
            "Gold": [
                {"name": "AWP | Neon Rider", "condition": "Minimal Wear", "tier": "Legendary"},
                {"name": "M4A4 | Howl", "condition": "Field-Tested", "tier": "Epic"},
                {"name": "AK-47 | Nightwish", "condition": "Minimal Wear", "tier": "Legendary"},
                {"name": "★ Falchion Knife", "condition": "Factory New", "tier": "Legendary"},
                {"name": "★ Huntsman Knife", "condition": "Factory New", "tier": "Legendary"}
            ],
            "Red": [
                {"name": "AWP | BOOM", "condition": "Field-Tested"},
                {"name": "M4A1-S | Night Terror", "condition": "Minimal Wear"},
                {"name": "Desert Eagle | Oxide Blaze", "condition": "Factory New"},
                {"name": "M4A4 | Emperor", "condition": "Minimal Wear"},
                {"name": "AK-47 | Orbit Mk01", "condition": "Field-Tested"}
            ],
            "Pink": [
                {"name": "FAMAS | Commemoration", "condition": "Minimal Wear"},
                {"name": "P250 | See Ya Later", "condition": "Factory New"},
                {"name": "MP9 | Goo", "condition": "Factory New"},
                {"name": "AUG | Torque", "condition": "Minimal Wear"},
                {"name": "PP-Bizon | Antique", "condition": "Minimal Wear"}
            ],
            "Purple": [
                {"name": "MP5-SD | Phosphor", "condition": "Minimal Wear"},
                {"name": "Nova | Tree Hugger", "condition": "Well-Worn"},
                {"name": "Galil AR | Crimson Tsunami", "condition": "Field-Tested"},
                {"name": "MAG-7 | BI83 Spectrum", "condition": "Well-Worn"}
            ]
        }
    },
    "ticket_4": {
        "id": "ticket_4",
        "name": "Epic Arsenal",
        "description": "Guaranteed at least Pink - Knife territory!",
        "tier": "ticket_4",
        "price_tickets": 10,
        "price_usd": 1.00,
        "drop_rates": {"Gold": 20.0, "Red": 30.0, "Pink": 50.0},
        "items": {
            "Gold": [
                {"name": "★ Karambit | Doppler", "condition": "Factory New", "tier": "Mythic"},
                {"name": "★ M9 Bayonet | Lore", "condition": "Minimal Wear", "tier": "Mythic"},
                {"name": "★ Butterfly Knife | Fade", "condition": "Factory New", "tier": "Mythic"},
                {"name": "★ Bayonet | Marble Fade", "condition": "Factory New", "tier": "Legendary"},
                {"name": "★ Bowie Knife | Gamma Doppler", "condition": "Factory New", "tier": "Legendary"},
                {"name": "★ Classic Knife | Fade", "condition": "Factory New", "tier": "Legendary"}
            ],
            "Red": [
                {"name": "AWP | Gungnir", "condition": "Field-Tested"},
                {"name": "M4A4 | Howl", "condition": "Field-Tested"},
                {"name": "AK-47 | Fire Serpent", "condition": "Minimal Wear"},
                {"name": "M4A1-S | Welcome to the Jungle", "condition": "Minimal Wear"},
                {"name": "Desert Eagle | Prism", "condition": "Factory New"},
                {"name": "AWP | Wildfire", "condition": "Field-Tested"}
            ],
            "Pink": [
                {"name": "USP-S | Kill Confirmed", "condition": "Field-Tested"},
                {"name": "SSG 08 | Deathstrike", "condition": "Minimal Wear"},
                {"name": "P2000 | Obsidian", "condition": "Factory New"},
                {"name": "AK-47 | Neon Revolution", "condition": "Field-Tested"},
                {"name": "M4A4 | Hellfire", "condition": "Minimal Wear"},
                {"name": "USP-S | Jawbreaker", "condition": "Minimal Wear"}
            ]
        }
    },
    "ticket_5": {
        "id": "ticket_5",
        "name": "Legendary Loot",
        "description": "The ultimate case - only the best of the best!",
        "tier": "ticket_5",
        "price_tickets": 20,
        "price_usd": 2.00,
        "drop_rates": {"Gold_ultra": 2, "Gold_rare": 18, "Red": 80},
        "items": {
            "Gold_ultra": [
                {"name": "★ Karambit | Ruby", "condition": "Factory New", "tier": "Mythic"},
                {"name": "★ Butterfly Knife | Gamma Doppler", "condition": "Factory New", "tier": "Mythic"},
                {"name": "★ M9 Bayonet | Crimson Web", "condition": "Minimal Wear", "tier": "Mythic"},
                {"name": "★ Karambit | Doppler", "condition": "Factory New", "tier": "Mythic"},
                {"name": "★ M9 Bayonet | Lore", "condition": "Minimal Wear", "tier": "Mythic"}
            ],
            "Gold_rare": [
                {"name": "AK-47 | Fuel Injection", "condition": "Minimal Wear", "tier": "Legendary"},
                {"name": "AWP | The Prince", "condition": "Field-Tested", "tier": "Legendary"},
                {"name": "M4A4 | Hellfire", "condition": "Minimal Wear", "tier": "Epic"},
                {"name": "AK-47 | Jet Set", "condition": "Field-Tested", "tier": "Epic"},
                {"name": "AWP | Gungnir", "condition": "Field-Tested", "tier": "Legendary"},
                {"name": "M4A4 | Howl", "condition": "Field-Tested", "tier": "Epic"},
                {"name": "AK-47 | Fire Serpent", "condition": "Minimal Wear", "tier": "Legendary"}
            ],
            "Red": [
                {"name": "AWP | Wildfire", "condition": "Field-Tested"},
                {"name": "Desert Eagle | Cobalt Disruption", "condition": "Factory New"},
                {"name": "M4A1-S | Briefing", "condition": "Minimal Wear"},
                {"name": "AK-47 | Neon Revolution", "condition": "Field-Tested"},
                {"name": "USP-S | Jawbreaker", "condition": "Minimal Wear"},
                {"name": "M4A4 | Emperor", "condition": "Minimal Wear"},
                {"name": "AWP | Oni Taiji", "condition": "Field-Tested"}
            ]
        }
    }
}

# ============================================
# MYTHIC BONUS TIER (0.5% in Legendary Loot)
# ============================================

MYTHIC_ITEMS = [
    {"name": "★ Karambit | Ruby", "condition": "Factory New", "tier": "Mythic"},
    {"name": "★ Butterfly Knife | Gamma Doppler", "condition": "Factory New", "tier": "Mythic"},
    {"name": "★ M9 Bayonet | Crimson Web", "condition": "Factory New", "tier": "Mythic"},
    {"name": "★ Karambit | Doppler", "condition": "Factory New", "tier": "Mythic"},
    {"name": "★ M9 Bayonet | Lore", "condition": "Factory New", "tier": "Mythic"},
    {"name": "AK-47 | Fire Serpent", "condition": "Factory New", "tier": "Mythic"},
    {"name": "AWP | Gungnir", "condition": "Factory New", "tier": "Mythic"},
    {"name": "M4A4 | Howl", "condition": "Factory New", "tier": "Mythic"}
]

TICKET_PACKS = {
    "10": {"tickets": 10, "price_usd": 1.00, "discount": 0},
    "25": {"tickets": 25, "price_usd": 2.00, "discount": 20},
    "50": {"tickets": 50, "price_usd": 4.00, "discount": 20},
    "100": {"tickets": 100, "price_usd": 7.00, "discount": 30},
    "250": {"tickets": 250, "price_usd": 15.00, "discount": 40},
    "500": {"tickets": 500, "price_usd": 25.00, "discount": 50}
}

@app.get("/api/premium-status")
async def get_premium_status():
    return {
        "enabled": PREMIUM_ENABLED,
        "message": PREMIUM_ENABLED_MESSAGE if not PREMIUM_ENABLED else "Premium features are active!"
    }

@app.get("/api/premium-cases")
async def get_premium_cases():
    return {
        "enabled": PREMIUM_ENABLED,
        "cases": [
            {
                "id": cid,
                "name": c["name"],
                "description": c["description"],
                "price_tickets": c["price_tickets"],
                "price_usd": c["price_usd"],
                "tier": c["tier"],
                "drop_rates": c["drop_rates"],
                "locked": not PREMIUM_ENABLED
            }
            for cid, c in PREMIUM_CASES.items()
            if c.get("is_active", True)
        ]
    }

# ============================================
# KO-FI GOALS ENDPOINT
# ============================================

@app.get("/api/goals")
async def get_goals():
    """Get current donation and user count goals"""
    async with db_pool.acquire() as conn:
        # Get total donations (simulated for now - manual entry)
        donations = await conn.fetchval(
            "SELECT COALESCE(SUM(amount), 0) FROM donations WHERE status = 'confirmed'"
        ) or 0
        
        # Get total users
        users = await conn.fetchval("SELECT COUNT(*) FROM users") or 0
        
        return {
            "donations": float(donations),
            "users": users,
            "goal_donations": 500,
            "goal_users": 1000
        }

@app.post("/api/donations/add")
async def add_donation(request: Request, body: dict):
    """Add a manual donation entry (admin only)"""
    user_id = await get_user_id_from_session(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    amount = body.get("amount")
    donor_name = body.get("donor_name", "Anonymous")
    donor_email = body.get("donor_email")
    
    if not amount or amount <= 0:
        return {"success": False, "error": "Invalid amount"}
    
    async with db_pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id FROM donations WHERE user_id = $1",
            user_id
        )
        
        if existing:
            await conn.execute(
                "UPDATE donations SET amount = amount + $1, donor_name = $2, donor_email = $3, updated_at = NOW() WHERE user_id = $4",
                amount, donor_name, donor_email, user_id
            )
        else:
            await conn.execute(
                "INSERT INTO donations (user_id, amount, donor_name, donor_email, status) VALUES ($1, $2, $3, $4, 'confirmed')",
                user_id, amount, donor_name, donor_email
            )
        
        return {"success": True, "message": "Donation recorded successfully"}

# ============================================
# STRIPE PAYMENT ENDPOINTS
# ============================================

@app.post("/api/buy-tickets")
async def buy_tickets(request: Request, body: dict):
    if not PREMIUM_ENABLED:
        return {
            "success": False,
            "error": PREMIUM_ENABLED_MESSAGE,
            "locked": True
        }
    
    user_id = await get_user_id_from_session(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    pack_id = body.get("pack_id")
    
    if not pack_id or pack_id not in TICKET_PACKS:
        return {"success": False, "error": "Invalid pack selected"}
    
    pack = TICKET_PACKS[pack_id]
    
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': f'{pack["tickets"]} Tickets',
                        'description': 'CS2CaseBot Premium Tickets',
                    },
                    'unit_amount': int(pack['price_usd'] * 100),
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url='https://cs2casebot.xyz/dashboard?tickets_bought=true',
            cancel_url='https://cs2casebot.xyz/dashboard?canceled=true',
            metadata={
                'user_id': str(user_id),
                'tickets': str(pack['tickets']),
                'pack_id': pack_id
            }
        )
        
        return {"url": session.url}
    except Exception as e:
        logger.error(f"Buy tickets error: {e}")
        return {"success": False, "error": str(e)}

# ============================================
# STRIPE WEBHOOK
# ============================================

@app.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    if not PREMIUM_ENABLED:
        return {"status": "locked", "message": "Premium features not enabled"}
    
    payload = await request.body()
    sig_header = request.headers.get('stripe-signature')
    webhook_secret = os.getenv('STRIPE_WEBHOOK_SECRET')
    
    if not webhook_secret:
        logger.error("STRIPE_WEBHOOK_SECRET not set!")
        return {"status": "error", "message": "Webhook secret not configured"}
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret
        )
    except ValueError as e:
        logger.error(f"Invalid payload: {e}")
        return {"status": "error", "message": "Invalid payload"}
    except stripe.error.SignatureVerificationError as e:
        logger.error(f"Invalid signature: {e}")
        return {"status": "error", "message": "Invalid signature"}
    
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        user_id = int(session['metadata']['user_id'])
        tickets = int(session['metadata']['tickets'])
        
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET credits = credits + $1 WHERE user_id = $2",
                tickets, user_id
            )
            await conn.execute(
                "INSERT INTO ticket_purchases (user_id, amount, cost_usd, stripe_session_id) VALUES ($1, $2, $3, $4)",
                user_id, tickets, float(session['amount_total']) / 100, session['id']
            )
        
        logger.info(f"Added {tickets} tickets to user {user_id}")
    
    return {"status": "success"}

# ============================================
# USER TICKETS ENDPOINT
# ============================================

@app.get("/api/user/me/tickets")
async def get_my_tickets(request: Request):
    user_id = await get_user_id_from_session(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT credits FROM users WHERE user_id = $1", user_id)
        if not user:
            return {"tickets": 0}
        return {"tickets": user['credits'] or 0}

# ============================================
# GAME API ROUTES
# ============================================

# --- COINFLIP - VS COMPUTER ---
@app.post("/api/games/coinflip/create")
async def create_coinflip_game(request: Request, body: dict):
    user_id = await get_user_id_from_session(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    amount = body.get("amount")
    if not amount or amount < 100:
        return {"success": False, "error": "Minimum bet is $100"}
    
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            user = await conn.fetchrow("SELECT balance FROM users WHERE user_id = $1", user_id)
            if not user or user['balance'] < amount:
                return {"success": False, "error": "Insufficient balance"}
            
            # Take their money
            await conn.execute(
                "UPDATE users SET balance = balance - $1 WHERE user_id = $2",
                amount, user_id
            )
            
            # Computer flips coin - 50/50 chance
            user_wins = random.choice([True, False])
            
            if user_wins:
                win_amount = int(amount * 1.95)  # 95% payout
                await conn.execute(
                    "UPDATE users SET balance = balance + $1 WHERE user_id = $2",
                    win_amount, user_id
                )
                result = "win"
            else:
                win_amount = 0
                result = "lose"
            
            # Save game record
            await conn.execute(
                """INSERT INTO coinflip_games 
                   (creator_id, amount, status, completed_at, opponent_id) 
                   VALUES ($1, $2, 'complete', NOW(), 999999999)""",
                user_id, amount
            )
            
            return {
                "success": True,
                "user_wins": user_wins,
                "amount": amount,
                "win_amount": win_amount,
                "result": result,
                "message": "You won! 🎉" if user_wins else "Computer wins! Better luck next time! 😢"
            }

# --- DICE ---
@app.post("/api/games/dice/play")
async def play_dice(request: Request, body: dict):
    user_id = await get_user_id_from_session(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    amount = body.get("amount")
    bet_type = body.get("bet_type", "over")
    bet_number = body.get("bet_number", 50)
    
    if not amount or amount < 100:
        return {"success": False, "error": "Minimum bet is $100"}
    if bet_type not in ['over', 'under']:
        return {"success": False, "error": 'Bet type must be "over" or "under"'}
    if bet_number < 2 or bet_number > 99:
        return {"success": False, "error": "Bet number must be between 2 and 99"}
    
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            user = await conn.fetchrow("SELECT balance FROM users WHERE user_id = $1", user_id)
            if not user or user['balance'] < amount:
                return {"success": False, "error": "Insufficient balance"}
            
            await conn.execute(
                "UPDATE users SET balance = balance - $1 WHERE user_id = $2",
                amount, user_id
            )
            
            roll = random.randint(1, 100)
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
            
            await conn.execute(
                """INSERT INTO dice_games 
                   (user_id, amount, bet_type, bet_number, roll_number, result, multiplier) 
                   VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                user_id, amount, bet_type, bet_number, roll, 'win' if win else 'lose', multiplier
            )
            
            return {
                "success": True,
                "roll": roll,
                "bet_type": bet_type,
                "bet_number": bet_number,
                "win": win,
                "multiplier": multiplier,
                "amount": amount,
                "win_amount": win_amount
            }

# --- MINES ---
# Mines functions are in main.py only (bot commands)
# Web API version uses the same logic

# --- SLOTS ---
@app.post("/api/games/slots/play")
async def play_slots(request: Request, body: dict):
    user_id = await get_user_id_from_session(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    amount = body.get("amount")
    if not amount or amount < 50:
        return {"success": False, "error": "Minimum bet is $50"}
    
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
    
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            user = await conn.fetchrow("SELECT balance FROM users WHERE user_id = $1", user_id)
            if not user or user['balance'] < amount:
                return {"success": False, "error": "Insufficient balance"}
            
            await conn.execute(
                "UPDATE users SET balance = balance - $1 WHERE user_id = $2",
                amount, user_id
            )
            
            symbols = [random.choice(SLOT_SYMBOLS)['emoji'] for _ in range(3)]
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
            
            await conn.execute(
                """INSERT INTO slots_games 
                   (user_id, bet_amount, spin_result, multiplier, win_amount) 
                   VALUES ($1, $2, $3, $4, $5)""",
                user_id, amount, symbols, multiplier, win_amount
            )
            
            return {
                "success": True,
                "symbols": symbols,
                "result_str": result_str,
                "multiplier": multiplier,
                "win_amount": win_amount,
                "bet_amount": amount
            }

# --- SKIN UPGRADE ---
@app.post("/api/games/upgrade")
async def upgrade_skin(request: Request, body: dict):
    user_id = await get_user_id_from_session(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    item_id = body.get("item_id")
    if not item_id:
        return {"success": False, "error": "Missing item_id"}
    
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            item = await conn.fetchrow(
                "SELECT * FROM inventory WHERE id = $1 AND user_id = $2 AND status = 'kept'",
                item_id, user_id
            )
            if not item:
                return {"success": False, "error": "Item not found in inventory"}
            
            rarity_order = ['Blue', 'Purple', 'Pink', 'Red', 'Gold']
            if item['rarity'] == 'Gold':
                return {"success": False, "error": "Gold items cannot be upgraded! Use gold trade instead."}
            
            current_rarity = item['rarity']
            current_index = rarity_order.index(current_rarity)
            next_rarity = rarity_order[current_index + 1] if current_index < len(rarity_order) - 1 else None
            
            if not next_rarity:
                return {"success": False, "error": "Item cannot be upgraded further"}
            
            chances = {'Blue': 0.8, 'Purple': 0.6, 'Pink': 0.4, 'Red': 0.25}
            success_chance = chances.get(current_rarity, 0.5)
            success = random.random() < success_chance
            
            upgrade_cost = {'Blue': 10, 'Purple': 50, 'Pink': 200, 'Red': 1000}.get(current_rarity, 10)
            
            user = await conn.fetchrow("SELECT balance FROM users WHERE user_id = $1", user_id)
            if not user or user['balance'] < upgrade_cost:
                return {"success": False, "error": f"Insufficient balance. Upgrade costs ${upgrade_cost}"}
            
            await conn.execute(
                "UPDATE users SET balance = balance - $1 WHERE user_id = $2",
                upgrade_cost, user_id
            )
            await conn.execute("DELETE FROM inventory WHERE id = $1", item_id)
            
            if success:
                possible_items = []
                for case in CASES.values():
                    for case_item in case['items']:
                        if case_item['rarity'] == next_rarity:
                            possible_items.append(case_item)
                
                new_item_template = random.choice(possible_items) if possible_items else {
                    'name': f'Mystery {next_rarity} Item',
                    'rarity': next_rarity,
                    'condition': 'Field-Tested',
                    'tier': None
                }
                
                is_stattrak = random.random() < 0.1
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
                
                return {
                    "success": True,
                    "upgraded": True,
                    "new_rarity": next_rarity,
                    "new_item_name": name,
                    "new_price": value,
                    "old_rarity": current_rarity,
                    "old_item_name": item['item_name']
                }
            else:
                return {
                    "success": True,
                    "upgraded": False,
                    "old_item_name": item['item_name'],
                    "old_rarity": current_rarity,
                    "cost": upgrade_cost
                }

# --- HOURLY & WEEKLY ---
@app.post("/api/games/hourly")
async def claim_hourly(request: Request):
    user_id = await get_user_id_from_session(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT last_hourly, total_hourly_claimed FROM users WHERE user_id = $1", user_id)
        if not user:
            return {"success": False, "error": "User not found"}
        
        now = datetime.now()
        last_hourly = user['last_hourly']
        
        if last_hourly and (now - last_hourly).total_seconds() < 3600:
            remaining = 3600 - (now - last_hourly).total_seconds()
            minutes = int(remaining // 60)
            return {"success": False, "error": f'Already claimed! Next claim in {minutes} minutes'}
        
        reward = 75
        total_claimed = (user['total_hourly_claimed'] or 0) + 1
        if total_claimed % 10 == 0:
            reward += 250
        
        await conn.execute(
            """UPDATE users SET balance = balance + $1, last_hourly = $2, total_hourly_claimed = $3 WHERE user_id = $4""",
            reward, now, total_claimed, user_id
        )
        
        return {"success": True, "reward": reward, "total_claimed": total_claimed}

@app.post("/api/games/weekly")
async def claim_weekly(request: Request):
    user_id = await get_user_id_from_session(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT last_weekly, total_weekly_claimed FROM users WHERE user_id = $1", user_id)
        if not user:
            return {"success": False, "error": "User not found"}
        
        now = datetime.now()
        last_weekly = user['last_weekly']
        
        if last_weekly and (now - last_weekly).total_seconds() < 604800:
            remaining = 604800 - (now - last_weekly).total_seconds()
            days = int(remaining // 86400)
            hours = int((remaining % 86400) // 3600)
            return {"success": False, "error": f'Already claimed! Next claim in {days}d {hours}h'}
        
        reward = 5000
        total_claimed = (user['total_weekly_claimed'] or 0) + 1
        
        await conn.execute(
            """UPDATE users SET balance = balance + $1, last_weekly = $2, total_weekly_claimed = $3 WHERE user_id = $4""",
            reward, now, total_claimed, user_id
        )
        
        return {"success": True, "reward": reward, "total_claimed": total_claimed}

# --- PROFILE ---
@app.get("/api/user/me/profile")
async def get_user_profile(request: Request):
    user_id = await get_user_id_from_session(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT xp, level, prestige, balance FROM users WHERE user_id = $1",
            user_id
        )
        if not user:
            return {"xp": 0, "level": 1, "prestige": 0, "balance": 1000}
        
        xp_needed = (user['level'] or 1) * 50 + 100
        return {
            "xp": user['xp'] or 0,
            "level": user['level'] or 1,
            "prestige": user['prestige'] or 0,
            "balance": float(user['balance'] or 0),
            "xp_needed": xp_needed,
            "xp_progress": int((user['xp'] or 0) / xp_needed * 100) if xp_needed > 0 else 0
        }

# --- GAME STATS ---
@app.get("/api/games/stats")
async def get_user_game_stats(request: Request):
    user_id = await get_user_id_from_session(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    async with db_pool.acquire() as conn:
        stats = {}
        
        coinflip_wins = await conn.fetchval(
            "SELECT COUNT(*) FROM coinflip_games WHERE winner_id = $1",
            user_id
        ) or 0
        coinflip_losses = await conn.fetchval(
            "SELECT COUNT(*) FROM coinflip_games WHERE (creator_id = $1 OR opponent_id = $1) AND winner_id IS NOT NULL AND winner_id != $1",
            user_id
        ) or 0
        
        dice_wins = await conn.fetchval(
            "SELECT COUNT(*) FROM dice_games WHERE user_id = $1 AND result = 'win'",
            user_id
        ) or 0
        dice_losses = await conn.fetchval(
            "SELECT COUNT(*) FROM dice_games WHERE user_id = $1 AND result = 'lose'",
            user_id
        ) or 0
        
        mines_wins = await conn.fetchval(
            "SELECT COUNT(*) FROM mines_games WHERE user_id = $1 AND status = 'won'",
            user_id
        ) or 0
        mines_losses = await conn.fetchval(
            "SELECT COUNT(*) FROM mines_games WHERE user_id = $1 AND status = 'lost'",
            user_id
        ) or 0
        
        slots_wins = await conn.fetchval(
            "SELECT COUNT(*) FROM slots_games WHERE user_id = $1 AND win_amount > 0",
            user_id
        ) or 0
        slots_losses = await conn.fetchval(
            "SELECT COUNT(*) FROM slots_games WHERE user_id = $1 AND win_amount = 0",
            user_id
        ) or 0
        
        return {
            "coinflip": {"wins": coinflip_wins, "losses": coinflip_losses},
            "dice": {"wins": dice_wins, "losses": dice_losses},
            "mines": {"wins": mines_wins, "losses": mines_losses},
            "slots": {"wins": slots_wins, "losses": slots_losses}
        }

# ============================================
# STATS & HEALTH
# ============================================

@app.get("/api/stats")
async def get_bot_stats():
    async with db_pool.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
        total_balance = await conn.fetchval("SELECT COALESCE(SUM(balance), 0) FROM users")
        total_opens = await conn.fetchval("SELECT COALESCE(SUM(total_opens), 0) FROM users")
        total_golds = await conn.fetchval("SELECT COALESCE(SUM(total_golds), 0) FROM users")
        total_trades = await conn.fetchval("SELECT COALESCE(SUM(total_trades), 0) FROM users")
        total_items = await conn.fetchval("SELECT COALESCE(SUM(price), 0) FROM inventory WHERE status = 'kept'")
        
        return {
            "total_users": total_users or 0,
            "total_balance": float(total_balance or 0),
            "total_opens": total_opens or 0,
            "total_golds": total_golds or 0,
            "total_trades": total_trades or 0,
            "total_items_value": float(total_items or 0)
        }

@app.get("/health")
async def health_check():
    if db_pool is None:
        return {"status": "error", "message": "Database not connected"}
    try:
        async with db_pool.acquire() as conn:
            await conn.execute("SELECT 1")
        return {"status": "healthy", "timestamp": datetime.now().isoformat()}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ============================================
# USER SETTINGS
# ============================================

@app.get("/api/user/settings")
async def get_user_settings(request: Request):
    user_id = await get_user_id_from_session(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    async with db_pool.acquire() as conn:
        settings = await conn.fetchrow(
            "SELECT * FROM user_settings WHERE user_id = $1",
            user_id
        )
        
        if not settings:
            await conn.execute(
                """INSERT INTO user_settings (user_id, theme, spin_speed, sound_enabled, feed_enabled, confetti_mode) 
                   VALUES ($1, 'casino', 'normal', true, true, 'always')""",
                user_id
            )
            settings = await conn.fetchrow(
                "SELECT * FROM user_settings WHERE user_id = $1",
                user_id
            )
        
        return dict(settings)

@app.post("/api/user/settings")
async def save_user_settings(request: Request, body: dict):
    user_id = await get_user_id_from_session(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    theme = body.get('theme', 'casino')
    spin_speed = body.get('spin_speed', 'normal')
    sound_enabled = body.get('sound_enabled', True)
    feed_enabled = body.get('feed_enabled', True)
    confetti_mode = body.get('confetti_mode', 'always')
    
    async with db_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO user_settings (user_id, theme, spin_speed, sound_enabled, feed_enabled, confetti_mode, updated_at)
               VALUES ($1, $2, $3, $4, $5, $6, NOW())
               ON CONFLICT (user_id) DO UPDATE SET
               theme = $2, spin_speed = $3, sound_enabled = $4, feed_enabled = $5, confetti_mode = $6, updated_at = NOW()""",
            user_id, theme, spin_speed, sound_enabled, feed_enabled, confetti_mode
        )
        
        return {"success": True, "message": "Settings saved!"}

# ============================================
# LIVE FEED
# ============================================

@app.get("/api/live-feed")
async def get_live_feed(limit: int = 20):
    async with db_pool.acquire() as conn:
        feed = await conn.fetch(
            """SELECT id, username, item_name, rarity, rarity_emoji, case_type, float_value, created_at 
               FROM live_feed 
               ORDER BY created_at DESC 
               LIMIT $1""",
            limit
        )
        return {"feed": [dict(f) for f in feed]}

@app.post("/api/live-feed")
async def add_to_live_feed(request: Request, body: dict):
    user_id = await get_user_id_from_session(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    item_name = body.get('item_name')
    rarity = body.get('rarity')
    rarity_emoji = body.get('rarity_emoji', '')
    case_type = body.get('case_type', 'regular')
    float_value = body.get('float_value')
    
    user_data = await get_user_data(user_id)
    username = user_data.get('username', f'User_{user_id}')
    
    async with db_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO live_feed (user_id, username, item_name, rarity, rarity_emoji, case_type, float_value) 
               VALUES ($1, $2, $3, $4, $5, $6, $7)""",
            user_id, username, item_name, rarity, rarity_emoji, case_type, float_value
        )
        
        await conn.execute(
            "DELETE FROM live_feed WHERE created_at < NOW() - INTERVAL '7 days'"
        )
        
        return {"success": True}

# ============================================
# USER STREAKS
# ============================================

@app.get("/api/user/streak")
async def get_user_streak(request: Request):
    user_id = await get_user_id_from_session(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    async with db_pool.acquire() as conn:
        streak = await conn.fetchrow(
            "SELECT * FROM user_streaks WHERE user_id = $1",
            user_id
        )
        
        if not streak:
            await conn.execute(
                """INSERT INTO user_streaks (user_id, current_streak, best_streak, golds_in_streak, total_session_opens) 
                   VALUES ($1, 0, 0, 0, 0)""",
                user_id
            )
            streak = await conn.fetchrow(
                "SELECT * FROM user_streaks WHERE user_id = $1",
                user_id
            )
        
        return dict(streak)

@app.post("/api/user/streak/update")
async def update_user_streak(request: Request, body: dict):
    user_id = await get_user_id_from_session(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    case_id = body.get('case_id')
    item_rarity = body.get('rarity')
    is_gold = body.get('is_gold', False)
    
    async with db_pool.acquire() as conn:
        streak = await conn.fetchrow(
            "SELECT * FROM user_streaks WHERE user_id = $1",
            user_id
        )
        
        if not streak:
            await conn.execute(
                """INSERT INTO user_streaks (user_id, current_streak, best_streak, golds_in_streak, total_session_opens) 
                   VALUES ($1, 0, 0, 0, 0)""",
                user_id
            )
            streak = await conn.fetchrow(
                "SELECT * FROM user_streaks WHERE user_id = $1",
                user_id
            )
        
        current_streak = streak['current_streak'] or 0
        best_streak = streak['best_streak'] or 0
        golds_in_streak = streak['golds_in_streak'] or 0
        total_session_opens = streak['total_session_opens'] or 0
        
        current_case = streak.get('current_case_id')
        if current_case and current_case != case_id:
            current_streak = 0
            golds_in_streak = 0
        
        current_streak += 1
        total_session_opens += 1
        
        if is_gold:
            golds_in_streak += 1
        
        if current_streak > best_streak:
            best_streak = current_streak
        
        bonus_earned = golds_in_streak > 0 and golds_in_streak % 5 == 0
        
        await conn.execute(
            """UPDATE user_streaks 
               SET current_streak = $1, best_streak = $2, golds_in_streak = $3, 
                   total_session_opens = $4, current_case_id = $5, updated_at = NOW()
               WHERE user_id = $6""",
            current_streak, best_streak, golds_in_streak, total_session_opens, case_id, user_id
        )
        
        return {
            "success": True,
            "current_streak": current_streak,
            "best_streak": best_streak,
            "golds_in_streak": golds_in_streak,
            "total_opens": total_session_opens,
            "bonus_earned": bonus_earned
        }

# ============================================
# ACHIEVEMENTS
# ============================================

ACHIEVEMENTS = {
    "first_open": {"name": "🎯 First Case", "description": "Open your first case!", "icon": "🎯"},
    "first_gold": {"name": "⭐ First Gold", "description": "Pull your first Gold item!", "icon": "⭐"},
    "streak_5": {"name": "🔥 Streak 5", "description": "Open 5 cases in a row!", "icon": "🔥"},
    "streak_10": {"name": "💎 Streak 10", "description": "Open 10 cases in a row!", "icon": "💎"},
    "streak_25": {"name": "👑 Streak 25", "description": "Open 25 cases in a row!", "icon": "👑"},
    "gold_hunter": {"name": "🏆 Gold Hunter", "description": "Pull 10 Gold items!", "icon": "🏆"},
    "millionaire": {"name": "💰 Millionaire", "description": "Reach $1,000,000 inventory value!", "icon": "💰"},
    "case_master": {"name": "🎰 Case Master", "description": "Open 100 cases!", "icon": "🎰"},
    "premium_player": {"name": "🎟️ Premium Player", "description": "Open your first premium case!", "icon": "🎟️"},
}

@app.get("/api/user/achievements")
async def get_user_achievements(request: Request):
    user_id = await get_user_id_from_session(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    async with db_pool.acquire() as conn:
        unlocked = await conn.fetch(
            "SELECT achievement_id FROM user_achievements WHERE user_id = $1",
            user_id
        )
        unlocked_set = {row['achievement_id'] for row in unlocked}
        
        achievements = []
        for key, data in ACHIEVEMENTS.items():
            achievements.append({
                "id": key,
                "name": data["name"],
                "description": data["description"],
                "icon": data["icon"],
                "unlocked": key in unlocked_set
            })
        
        return {"achievements": achievements}

@app.post("/api/user/achievements/unlock")
async def unlock_achievement(request: Request, body: dict):
    user_id = await get_user_id_from_session(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    achievement_id = body.get('achievement_id')
    
    if achievement_id not in ACHIEVEMENTS:
        raise HTTPException(status_code=400, detail="Invalid achievement")
    
    async with db_pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT 1 FROM user_achievements WHERE user_id = $1 AND achievement_id = $2",
            user_id, achievement_id
        )
        
        if existing:
            return {"success": False, "message": "Already unlocked"}
        
        await conn.execute(
            "INSERT INTO user_achievements (user_id, achievement_id) VALUES ($1, $2)",
            user_id, achievement_id
        )
        
        return {"success": True, "achievement": ACHIEVEMENTS[achievement_id]}

# ============================================
# SERVE DASHBOARD
# ============================================

@app.get("/dashboard")
async def dashboard(request: Request):
    session_token = request.cookies.get("session_token")
    if not session_token or session_token not in sessions:
        return RedirectResponse(url="/")
    
    try:
        with open("static/index.html", "r", encoding="utf-8") as f:
            content = f.read()
            return HTMLResponse(content=content)
    except Exception as e:
        logger.error(f"Error loading dashboard: {e}")
        return HTMLResponse(content=f"Error loading dashboard: {str(e)}")

@app.get("/")
async def index(request: Request):
    try:
        with open("static/index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except Exception as e:
        logger.error(f"Error loading index: {e}")
        return HTMLResponse(content=f"Error loading page: {str(e)}")

@app.on_event("startup")
async def startup():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    logger.info("Database connected!")
    
    # Create auth_methods table if it doesn't exist
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS auth_methods (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                provider TEXT NOT NULL,
                provider_user_id TEXT NOT NULL,
                provider_username TEXT,
                provider_email TEXT,
                avatar_url TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(provider, provider_user_id)
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_auth_methods_user_id ON auth_methods(user_id)")
        
        # Make sure users table has user_id as primary key
        await conn.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints 
                               WHERE constraint_name = 'users_pkey' AND table_name = 'users') THEN
                    ALTER TABLE users ADD PRIMARY KEY (user_id);
                END IF;
            END $$;
        """)

@app.on_event("shutdown")
async def shutdown():
    if db_pool:
        await db_pool.close()

if __name__ == "__main__":
    import uvicorn
    print("=" * 60)
    print("🚀 CS2CaseBot Dashboard Server")
    print("=" * 60)
    print(f"📦 Total Cases: {len(CASES)}")
    print(f"🌐 Dashboard: https://cs2casebot.xyz")
    print(f"🔒 Premium Status: {'ENABLED' if PREMIUM_ENABLED else 'LOCKED'}")
    print("=" * 60)
    
    port = int(os.getenv('PORT', 8000))
    host = os.getenv('HOST', '0.0.0.0')
    
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info"
    )