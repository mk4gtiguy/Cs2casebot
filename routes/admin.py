# ============================================================
# routes/admin.py
# CS2CaseBot | Admin Panel API
#
# All routes prefixed /api/admin
# Every route requires the caller to be in ADMIN_USER_IDS.
#
# Endpoints (matching admin.html api() calls):
#   GET  /stats              — dashboard KPIs
#   GET  /users              — paginated user list with search
#   GET  /users/{id}         — user detail + inventory summary
#   POST /users/{id}/balance — adjust balance (+ or -)
#   POST /users/{id}/ban     — ban user
#   POST /users/{id}/unban   — unban user
#   GET  /cases              — all cases with price/featured
#   POST /cases/{id}/price   — update case price
#   POST /cases/{id}/featured— toggle featured flag
#   GET  /analytics/economy  — economy health stats
#   GET  /games/settings     — per-game settings
#   POST /games/settings     — update a game setting
#   GET  /giveaways          — list giveaways
#   POST /giveaway/create    — create giveaway
#   POST /giveaways/{id}/draw— draw winners
#   POST /inventory/deposit  — secret item deposit (+ Discord DM)
#   GET  /announcements      — list announcements
#   POST /announcements      — create announcement
#   GET  /settings           — site-wide settings
#   POST /settings           — save settings
#   GET  /audit-log          — paginated audit log
#   POST /beta/users         — add beta tester
#   GET  /live-feed          — recent case opens
#   POST /premium/toggle     — toggle premium mode
#   GET  /backup/create      — trigger DB backup
#   POST /fire-sale          — start a fire sale discount
# ============================================================

import asyncio
import json
import os
from datetime import datetime, timedelta
from typing import Optional, Any

from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel

import shared
from shared import (
    logger, get_db, require_auth, ADMIN_USER_IDS,
    deduct_balance, add_balance, convert_decimals, CASES,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])

# ── Admin guard ───────────────────────────────────────────────
async def require_admin(request: Request) -> int:
    """Dependency: must be logged in AND in ADMIN_USER_IDS."""
    user_id = await require_auth(request)
    if user_id not in ADMIN_USER_IDS:
        raise HTTPException(403, "Admin access required")
    return user_id

# ── Audit logger ─────────────────────────────────────────────
async def audit(conn, admin_id: int, action_type: str,
                target_id: int = None, target_username: str = None,
                details: dict = None):
    try:
        admin_row = await conn.fetchrow(
            "SELECT username FROM users WHERE user_id=$1", admin_id
        )
        admin_username = admin_row["username"] if admin_row else str(admin_id)
        await conn.execute("""
            INSERT INTO admin_audit_log
                (admin_id, admin_username, action_type,
                 target_id, target_username, details)
            VALUES ($1,$2,$3,$4,$5,$6)
        """, admin_id, admin_username, action_type,
            target_id, target_username,
            json.dumps(details or {}))
    except Exception as e:
        logger.warning(f"Audit log failed: {e}")

# ── Settings helpers ─────────────────────────────────────────
_settings_cache: dict = {}

async def get_settings(conn) -> dict:
    rows = await conn.fetch("SELECT key, value FROM admin_settings")
    return {r["key"]: r["value"] for r in rows}

async def set_setting(conn, key: str, value: str):
    await conn.execute("""
        INSERT INTO admin_settings (key, value)
        VALUES ($1,$2)
        ON CONFLICT (key) DO UPDATE SET value=$2, updated_at=NOW()
    """, key, value)

# ============================================================
# DASHBOARD — /stats
# ============================================================

@router.get("/stats")
async def admin_stats(admin_id: int = Depends(require_admin)):
    pool = await get_db()
    async with pool.acquire() as conn:
        # Users
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users") or 0
        new_24h     = await conn.fetchval(
            "SELECT COUNT(*) FROM users WHERE created_at > NOW() - INTERVAL '24 hours'"
        ) or 0
        total_bal   = await conn.fetchval(
            "SELECT COALESCE(SUM(balance),0) FROM users"
        ) or 0

        # Case opens
        total_opens = await conn.fetchval(
            "SELECT COALESCE(SUM(total_opens),0) FROM users"
        ) or 0
        opens_24h   = await conn.fetchval(
            "SELECT COUNT(*) FROM case_open_log WHERE opened_at > NOW() - INTERVAL '24 hours'"
        ) or 0

        # Revenue (sum of all bets placed)
        total_rev = await conn.fetchval(
            "SELECT COALESCE(SUM(bet_amount),0) FROM game_logs"
        ) or 0
        rev_30d   = await conn.fetchval(
            "SELECT COALESCE(SUM(bet_amount),0) FROM game_logs "
            "WHERE created_at > NOW() - INTERVAL '30 days'"
        ) or 0

    return {
        "users": {
            "total_users": int(total_users),
            "new_users_24h": int(new_24h),
            "total_balance_in_economy": float(total_bal),
        },
        "case_opens": {
            "total_opens": int(total_opens),
            "opens_24h":   int(opens_24h),
        },
        "revenue": {
            "total_revenue": float(total_rev),
            "revenue_30d":   float(rev_30d),
        },
    }

# ============================================================
# USERS
# ============================================================

@router.get("/users")
async def admin_users(
    limit: int = 20, offset: int = 0, search: str = "",
    admin_id: int = Depends(require_admin)
):
    pool = await get_db()
    async with pool.acquire() as conn:
        if search:
            rows = await conn.fetch("""
                SELECT user_id, username, balance, total_opens,
                       level, prestige, is_banned
                FROM users
                WHERE username ILIKE $1 OR user_id::text = $2
                ORDER BY balance DESC LIMIT $3 OFFSET $4
            """, f"%{search}%", search.strip(), limit, offset)
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM users WHERE username ILIKE $1 OR user_id::text=$2",
                f"%{search}%", search.strip()
            )
        else:
            rows = await conn.fetch("""
                SELECT user_id, username, balance, total_opens,
                       level, prestige, is_banned
                FROM users ORDER BY balance DESC LIMIT $1 OFFSET $2
            """, limit, offset)
            total = await conn.fetchval("SELECT COUNT(*) FROM users")

    return {
        "users": [convert_decimals(dict(r)) for r in rows],
        "total": int(total or 0),
        "limit": limit,
        "offset": offset,
    }

@router.get("/users/{user_id}")
async def admin_user_detail(
    user_id: int, admin_id: int = Depends(require_admin)
):
    pool = await get_db()
    async with pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT * FROM users WHERE user_id=$1", user_id
        )
        if not user:
            raise HTTPException(404, "User not found")

        inv_total = await conn.fetchval(
            "SELECT COUNT(*) FROM inventory WHERE user_id=$1", user_id
        ) or 0
        inv_value = await conn.fetchval(
            "SELECT COALESCE(SUM(price),0) FROM inventory WHERE user_id=$1", user_id
        ) or 0

    return {
        "user": convert_decimals(dict(user)),
        "inventory_summary": {
            "total_items": int(inv_total),
            "total_value": float(inv_value),
        },
    }

class BalanceAdjust(BaseModel):
    amount:  float
    reason:  str = "Admin adjustment"

@router.post("/users/{user_id}/balance")
async def admin_adjust_balance(
    user_id: int, body: BalanceAdjust,
    request: Request, admin_id: int = Depends(require_admin)
):
    pool = await get_db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            if body.amount >= 0:
                await add_balance(user_id, body.amount, conn)
            else:
                # Negative = deduction (ignore balance check for admin)
                await conn.execute(
                    "UPDATE users SET balance = GREATEST(0, balance + $1) WHERE user_id=$2",
                    body.amount, user_id
                )
            new_bal = await conn.fetchval(
                "SELECT balance FROM users WHERE user_id=$1", user_id
            )
            user = await conn.fetchrow(
                "SELECT username FROM users WHERE user_id=$1", user_id
            )
            await audit(conn, admin_id, "balance_adjust",
                       target_id=user_id,
                       target_username=user["username"] if user else None,
                       details={"amount": body.amount, "reason": body.reason})
    return {"success": True, "new_balance": float(new_bal or 0)}

class BanBody(BaseModel):
    reason:        str = "Admin ban"
    duration_days: Optional[int] = None

@router.post("/users/{user_id}/ban")
async def admin_ban_user(
    user_id: int, body: BanBody,
    request: Request, admin_id: int = Depends(require_admin)
):
    expires = None
    if body.duration_days:
        expires = datetime.utcnow() + timedelta(days=body.duration_days)
    pool = await get_db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE users SET is_banned=TRUE, ban_reason=$1, ban_expires=$2 WHERE user_id=$3",
                body.reason, expires, user_id
            )
            user = await conn.fetchrow("SELECT username FROM users WHERE user_id=$1", user_id)
            await audit(conn, admin_id, "ban",
                       target_id=user_id,
                       target_username=user["username"] if user else None,
                       details={"reason": body.reason, "duration_days": body.duration_days})
    return {"success": True}

@router.post("/users/{user_id}/unban")
async def admin_unban_user(
    user_id: int, request: Request, admin_id: int = Depends(require_admin)
):
    pool = await get_db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE users SET is_banned=FALSE, ban_reason=NULL, ban_expires=NULL WHERE user_id=$1",
                user_id
            )
            user = await conn.fetchrow("SELECT username FROM users WHERE user_id=$1", user_id)
            await audit(conn, admin_id, "unban",
                       target_id=user_id,
                       target_username=user["username"] if user else None)
    return {"success": True}

# ============================================================
# CASES
# ============================================================

@router.get("/cases")
async def admin_cases(admin_id: int = Depends(require_admin)):
    pool = await get_db()
    async with pool.acquire() as conn:
        # Merge in-memory CASES with any DB overrides
        rows = await conn.fetch("SELECT id, price, featured FROM case_prices")
        price_map    = {r["id"]: float(r["price"])      for r in rows}
        featured_map = {r["id"]: bool(r["featured"])    for r in rows}

    return {
        "cases": [
            {
                "id":       c["id"],
                "name":     c["name"],
                "emoji":    c.get("emoji", "📦"),
                "price":    price_map.get(c["id"], float(c.get("price", 1000))),
                "featured": featured_map.get(c["id"], False),
            }
            for c in CASES
        ]
    }

class PriceBody(BaseModel):
    price: float

@router.post("/cases/{case_id}/price")
async def admin_update_case_price(
    case_id: str, body: PriceBody,
    request: Request, admin_id: int = Depends(require_admin)
):
    if body.price <= 0:
        raise HTTPException(400, "Price must be positive")
    pool = await get_db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("""
                INSERT INTO case_prices (id, price)
                VALUES ($1,$2)
                ON CONFLICT (id) DO UPDATE SET price=$2, updated_at=NOW()
            """, case_id, body.price)
            await audit(conn, admin_id, "update_case_price",
                       details={"case_id": case_id, "price": body.price})
    return {"success": True}

class FeaturedBody(BaseModel):
    featured: bool

@router.post("/cases/{case_id}/featured")
async def admin_toggle_featured(
    case_id: str, body: FeaturedBody,
    request: Request, admin_id: int = Depends(require_admin)
):
    pool = await get_db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("""
                INSERT INTO case_prices (id, featured)
                VALUES ($1,$2)
                ON CONFLICT (id) DO UPDATE SET featured=$2, updated_at=NOW()
            """, case_id, body.featured)
            await audit(conn, admin_id, "toggle_featured",
                       details={"case_id": case_id, "featured": body.featured})
    return {"success": True}

# ============================================================
# ECONOMY / ANALYTICS
# ============================================================

@router.get("/analytics/economy")
async def admin_economy(admin_id: int = Depends(require_admin)):
    pool = await get_db()
    async with pool.acquire() as conn:
        total_bal   = await conn.fetchval("SELECT COALESCE(SUM(balance),0) FROM users") or 0
        avg_bal     = await conn.fetchval("SELECT COALESCE(AVG(balance),0) FROM users") or 0
        inv_val     = await conn.fetchval(
            "SELECT COALESCE(SUM(price),0) FROM inventory"
        ) or 0
        total_opens = await conn.fetchval(
            "SELECT COALESCE(SUM(total_opens),0) FROM users"
        ) or 0
        total_golds = await conn.fetchval(
            "SELECT COALESCE(SUM(gold_count),0) FROM users"
        ) or 0
    return {
        "total_balance":         float(total_bal),
        "avg_balance":           float(avg_bal),
        "total_inventory_value": float(inv_val),
        "total_cases_opened":    int(total_opens),
        "total_golds":           int(total_golds),
    }

# ============================================================
# GAME SETTINGS
# ============================================================

@router.get("/games/settings")
async def admin_game_settings(admin_id: int = Depends(require_admin)):
    pool = await get_db()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT game_name, settings FROM game_settings")
    settings = {}
    for r in rows:
        try:
            settings[r["game_name"]] = json.loads(r["settings"])
        except Exception:
            settings[r["game_name"]] = {}
    # Add defaults for any missing games
    defaults = ["slots", "coinflip", "dice", "crash", "mines", "plinko",
                "tower", "blackjack", "roulette", "baccarat", "poker"]
    for g in defaults:
        if g not in settings:
            settings[g] = {"enabled": "true", "house_edge": "0.04"}
    return {"settings": settings}

class GameSettingBody(BaseModel):
    game_name: str
    settings:  dict

@router.post("/games/settings")
async def admin_update_game_settings(
    body: GameSettingBody,
    request: Request, admin_id: int = Depends(require_admin)
):
    pool = await get_db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Merge with existing
            existing = await conn.fetchval(
                "SELECT settings FROM game_settings WHERE game_name=$1", body.game_name
            )
            current = json.loads(existing) if existing else {}
            current.update(body.settings)
            await conn.execute("""
                INSERT INTO game_settings (game_name, settings)
                VALUES ($1,$2)
                ON CONFLICT (game_name) DO UPDATE SET settings=$2, updated_at=NOW()
            """, body.game_name, json.dumps(current))
            await audit(conn, admin_id, "update_game_settings",
                       details={"game": body.game_name, "changes": body.settings})
    return {"success": True}

# ============================================================
# GIVEAWAYS
# ============================================================

@router.get("/giveaways")
async def admin_giveaways(admin_id: int = Depends(require_admin)):
    pool = await get_db()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT g.*, COUNT(e.id) as entries_count
            FROM giveaways g
            LEFT JOIN giveaway_entries e ON e.giveaway_id = g.id
            GROUP BY g.id ORDER BY g.created_at DESC LIMIT 50
        """)
    return {"giveaways": [convert_decimals(dict(r)) for r in rows]}

class GiveawayBody(BaseModel):
    prize_amount:    float
    winner_count:    int   = 1
    duration_minutes: int  = 60
    required_level:  int   = 0
    required_opens:  int   = 0

@router.post("/giveaway/create")
async def admin_create_giveaway(
    body: GiveawayBody,
    request: Request, admin_id: int = Depends(require_admin)
):
    end_time = datetime.utcnow() + timedelta(minutes=body.duration_minutes)
    pool = await get_db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("""
                INSERT INTO giveaways
                    (prize_amount, winner_count, end_time,
                     required_level, required_opens, status, created_by)
                VALUES ($1,$2,$3,$4,$5,'active',$6)
                RETURNING id
            """, body.prize_amount, body.winner_count, end_time,
                body.required_level, body.required_opens, admin_id)
            await audit(conn, admin_id, "create_giveaway",
                       details={"prize": body.prize_amount, "winners": body.winner_count})
    return {"success": True, "giveaway_id": row["id"]}

@router.post("/giveaways/{giveaway_id}/draw")
async def admin_draw_giveaway(
    giveaway_id: int,
    request: Request, admin_id: int = Depends(require_admin)
):
    pool = await get_db()
    async with pool.acquire() as conn:
        giveaway = await conn.fetchrow(
            "SELECT * FROM giveaways WHERE id=$1", giveaway_id
        )
        if not giveaway:
            raise HTTPException(404, "Giveaway not found")
        if giveaway["status"] != "active":
            return {"success": False, "error": "Giveaway already drawn or cancelled"}

        entries = await conn.fetch(
            "SELECT user_id FROM giveaway_entries WHERE giveaway_id=$1", giveaway_id
        )
        if not entries:
            return {"success": False, "error": "No entries yet"}

        import random
        entry_ids = [e["user_id"] for e in entries]
        n_winners = min(giveaway["winner_count"], len(entry_ids))
        winners   = random.sample(entry_ids, n_winners)
        prize_each = float(giveaway["prize_amount"]) / n_winners

        async with conn.transaction():
            for uid in winners:
                await add_balance(uid, prize_each, conn)

            await conn.execute(
                "UPDATE giveaways SET status='completed', drawn_at=NOW() WHERE id=$1",
                giveaway_id
            )
            await audit(conn, admin_id, "draw_giveaway",
                       details={"giveaway_id": giveaway_id, "winners": winners,
                                "prize_each": prize_each})

    return {"success": True, "winners": winners, "prize_each": prize_each}

# ============================================================
# SECRET INVENTORY DEPOSIT
# ============================================================

class DepositBody(BaseModel):
    user_id:          int
    item_name:        str
    rarity:           str = "Blue"
    condition:        str = "Field-Tested"
    is_stattrak:      bool = False
    custom_price:     Optional[float] = None
    custom_message:   str = "Thanks for playing CS2CaseBot! 🎉"
    send_notification: bool = True

@router.post("/inventory/deposit")
async def admin_inventory_deposit(
    body: DepositBody,
    request: Request, admin_id: int = Depends(require_admin)
):
    RARITY_PRICES = {
        "Blue": 500, "Purple": 2000, "Pink": 5000,
        "Red": 15000, "Gold": 50000,
    }
    price = body.custom_price or RARITY_PRICES.get(body.rarity, 500)

    pool = await get_db()
    async with pool.acquire() as conn:
        # Check user exists
        user = await conn.fetchrow(
            "SELECT username FROM users WHERE user_id=$1", body.user_id
        )
        if not user:
            raise HTTPException(404, "User not found")

        async with conn.transaction():
            await conn.execute("""
                INSERT INTO inventory
                    (user_id, item_name, rarity, condition,
                     is_stattrak, price, source, acquired_at)
                VALUES ($1,$2,$3,$4,$5,$6,'admin_deposit',NOW())
            """, body.user_id, body.item_name, body.rarity,
                body.condition, body.is_stattrak, price)

            await audit(conn, admin_id, "inventory_deposit",
                       target_id=body.user_id,
                       target_username=user["username"],
                       details={
                           "item": body.item_name,
                           "rarity": body.rarity,
                           "price": price,
                       })

    # Try to DM user via Discord bot if notification requested
    if body.send_notification:
        try:
            # shared.bot_notify is set by main.py if the bot is running
            if hasattr(shared, 'bot_notify') and shared.bot_notify:
                await shared.bot_notify(
                    body.user_id,
                    f"🎁 **Secret Gift!**\n"
                    f"An admin deposited **{body.item_name}** "
                    f"({body.rarity}) into your inventory!\n"
                    f"{body.custom_message}"
                )
        except Exception as e:
            logger.warning(f"Could not DM user {body.user_id}: {e}")

    return {
        "success": True,
        "message": f"✅ {body.item_name} deposited to {user['username']}'s inventory",
    }

# ============================================================
# ANNOUNCEMENTS
# ============================================================

@router.get("/announcements")
async def admin_announcements(admin_id: int = Depends(require_admin)):
    pool = await get_db()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM announcements ORDER BY created_at DESC LIMIT 50"
        )
    return {"announcements": [convert_decimals(dict(r)) for r in rows]}

class AnnouncementBody(BaseModel):
    title:   str
    message: str
    type:    str = "info"   # info | warning | event

@router.post("/announcements")
async def admin_create_announcement(
    body: AnnouncementBody,
    request: Request, admin_id: int = Depends(require_admin)
):
    pool = await get_db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("""
                INSERT INTO announcements (title, message, type, created_by)
                VALUES ($1,$2,$3,$4) RETURNING id
            """, body.title, body.message, body.type, admin_id)
            await audit(conn, admin_id, "create_announcement",
                       details={"title": body.title, "type": body.type})
    return {"success": True, "id": row["id"]}

# ============================================================
# SETTINGS
# ============================================================

@router.get("/settings")
async def admin_get_settings(admin_id: int = Depends(require_admin)):
    pool = await get_db()
    async with pool.acquire() as conn:
        settings = await get_settings(conn)
    # Defaults
    defaults = {
        "site_name": "CS2CaseBot",
        "default_currency": "$",
        "support_discord_link": "https://discord.gg/mU33pc7TDE",
        "maintenance_mode": "false",
        "maintenance_message": "We'll be back soon!",
    }
    defaults.update(settings)
    return {"settings": defaults}

@router.post("/settings")
async def admin_save_settings(
    request: Request, admin_id: int = Depends(require_admin)
):
    body = await request.json()
    pool = await get_db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            for key, value in body.items():
                await set_setting(conn, key, str(value))
            await audit(conn, admin_id, "update_settings",
                       details={"keys": list(body.keys())})
    return {"success": True}

# ============================================================
# AUDIT LOG
# ============================================================

@router.get("/audit-log")
async def admin_audit_log(
    limit: int = 20, offset: int = 0,
    action_type: str = "",
    admin_id: int = Depends(require_admin)
):
    pool = await get_db()
    async with pool.acquire() as conn:
        if action_type:
            rows = await conn.fetch("""
                SELECT * FROM admin_audit_log
                WHERE action_type=$1
                ORDER BY created_at DESC LIMIT $2 OFFSET $3
            """, action_type, limit, offset)
        else:
            rows = await conn.fetch("""
                SELECT * FROM admin_audit_log
                ORDER BY created_at DESC LIMIT $1 OFFSET $2
            """, limit, offset)
    return {"logs": [convert_decimals(dict(r)) for r in rows]}

# ============================================================
# BETA TESTERS
# ============================================================

class BetaUserBody(BaseModel):
    user_id: int

@router.post("/beta/users")
async def admin_add_beta(
    body: BetaUserBody,
    request: Request, admin_id: int = Depends(require_admin)
):
    pool = await get_db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("""
                INSERT INTO beta_testers (user_id, added_by)
                VALUES ($1,$2)
                ON CONFLICT (user_id) DO NOTHING
            """, body.user_id, admin_id)
            await audit(conn, admin_id, "add_beta_tester",
                       target_id=body.user_id)
    return {"success": True}

# ============================================================
# LIVE FEED
# ============================================================

@router.get("/live-feed")
async def admin_live_feed(
    limit: int = 20,
    admin_id: int = Depends(require_admin)
):
    pool = await get_db()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT l.*, u.username
            FROM case_open_log l
            JOIN users u ON u.user_id = l.user_id
            ORDER BY l.opened_at DESC LIMIT $1
        """, limit)
    return {"feed": [convert_decimals(dict(r)) for r in rows]}

# ============================================================
# PREMIUM TOGGLE
# ============================================================

@router.post("/premium/toggle")
async def admin_toggle_premium(
    request: Request, admin_id: int = Depends(require_admin)
):
    pool = await get_db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            current = await conn.fetchval(
                "SELECT value FROM admin_settings WHERE key='premium_enabled'"
            )
            new_val = "false" if current == "true" else "true"
            await set_setting(conn, "premium_enabled", new_val)
            await audit(conn, admin_id, "toggle_premium",
                       details={"enabled": new_val})
    return {"success": True, "premium_enabled": new_val == "true"}

# ============================================================
# BACKUP
# ============================================================

@router.get("/backup/create")
async def admin_create_backup(
    request: Request, admin_id: int = Depends(require_admin)
):
    """Trigger a pg_dump backup of the database."""
    import subprocess, shutil
    pg_dump = shutil.which("pg_dump")
    if not pg_dump:
        raise HTTPException(500, "pg_dump not available")

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename  = f"backup_{timestamp}.sql"
    out_path  = f"/tmp/{filename}"

    db_url = os.getenv("DATABASE_URL", "")
    try:
        subprocess.run(
            [pg_dump, db_url, "-f", out_path],
            check=True, capture_output=True, timeout=60
        )
    except Exception as e:
        raise HTTPException(500, f"Backup failed: {e}")

    pool = await get_db()
    async with pool.acquire() as conn:
        await audit(conn, admin_id, "create_backup",
                   details={"filename": filename})

    return {"success": True, "filename": filename}

# ============================================================
# FIRE SALE
# ============================================================

class FireSaleBody(BaseModel):
    name:             str
    discount_percent: int
    duration_hours:   int
    case_type:        Optional[str] = None

@router.post("/fire-sale")
async def admin_fire_sale(
    body: FireSaleBody,
    request: Request, admin_id: int = Depends(require_admin)
):
    if not 1 <= body.discount_percent <= 90:
        raise HTTPException(400, "Discount must be 1–90%")

    expires_at = datetime.utcnow() + timedelta(hours=body.duration_hours)
    pool = await get_db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("""
                INSERT INTO fire_sales
                    (name, discount_percent, case_type, expires_at, created_by)
                VALUES ($1,$2,$3,$4,$5)
            """, body.name, body.discount_percent, body.case_type,
                expires_at, admin_id)
            await audit(conn, admin_id, "start_fire_sale",
                       details={
                           "name": body.name,
                           "discount": body.discount_percent,
                           "hours": body.duration_hours,
                       })
    return {"success": True}

# ============================================================
# DB TABLE INIT — called from server.py lifespan
# ============================================================

async def init_admin_tables():
    """Create all admin-specific tables if they don't exist."""
    pool = await get_db()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS admin_audit_log (
                id            BIGSERIAL PRIMARY KEY,
                admin_id      BIGINT,
                admin_username TEXT,
                action_type   TEXT NOT NULL,
                target_id     BIGINT,
                target_username TEXT,
                details       JSONB DEFAULT '{}',
                created_at    TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_audit_admin ON admin_audit_log(admin_id);
            CREATE INDEX IF NOT EXISTS idx_audit_time  ON admin_audit_log(created_at DESC);

            CREATE TABLE IF NOT EXISTS admin_settings (
                key        TEXT PRIMARY KEY,
                value      TEXT NOT NULL DEFAULT '',
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS game_settings (
                game_name  TEXT PRIMARY KEY,
                settings   JSONB DEFAULT '{}',
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS case_prices (
                id         TEXT PRIMARY KEY,
                price      NUMERIC(12,2),
                featured   BOOLEAN DEFAULT FALSE,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS giveaways (
                id             BIGSERIAL PRIMARY KEY,
                prize_amount   NUMERIC(12,2) NOT NULL,
                winner_count   INT DEFAULT 1,
                end_time       TIMESTAMPTZ NOT NULL,
                required_level INT DEFAULT 0,
                required_opens INT DEFAULT 0,
                status         TEXT DEFAULT 'active',
                drawn_at       TIMESTAMPTZ,
                created_by     BIGINT,
                created_at     TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS giveaway_entries (
                id           BIGSERIAL PRIMARY KEY,
                giveaway_id  BIGINT REFERENCES giveaways(id) ON DELETE CASCADE,
                user_id      BIGINT,
                entered_at   TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(giveaway_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS announcements (
                id         BIGSERIAL PRIMARY KEY,
                title      TEXT NOT NULL,
                message    TEXT NOT NULL,
                type       TEXT DEFAULT 'info',
                created_by BIGINT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS beta_testers (
                user_id  BIGINT PRIMARY KEY,
                added_by BIGINT,
                added_at TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS fire_sales (
                id               BIGSERIAL PRIMARY KEY,
                name             TEXT NOT NULL,
                discount_percent INT NOT NULL,
                case_type        TEXT,
                expires_at       TIMESTAMPTZ NOT NULL,
                created_by       BIGINT,
                created_at       TIMESTAMPTZ DEFAULT NOW()
            );
        """)
    logger.info("✅ Admin tables ready")
