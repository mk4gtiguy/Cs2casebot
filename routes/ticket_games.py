import json
import random
import secrets
from fastapi import APIRouter, HTTPException, Request
from shared import get_db, require_auth, logger, SKINS_DATA, ITEM_ID_TO_DISPLAY_NAME

router = APIRouter()

# Payout tiers — (threshold, tickets_won)
REACTION_TIERS = [(150, 8), (200, 5), (300, 3), (450, 2), (600, 1)]
AIM_TIERS      = [(20, 6), (18, 4), (15, 3), (10, 2), (5, 1)]
MEMORY_TIERS   = [(8, 6), (6, 4), (4, 3), (2, 1)]
FLOAT_TIERS    = [(0.01, 8), (0.03, 5), (0.05, 3), (0.10, 1)]
WIRE_COLORS    = ["red", "blue", "green", "yellow", "white"]


async def _start_game(user_id: int, game_type: str, game_data: dict, conn) -> str:
    tix = await conn.fetchval("SELECT tickets FROM users WHERE user_id=$1 FOR UPDATE", user_id)
    if (tix or 0) < 1:
        raise HTTPException(400, "Not enough tickets")
    token = secrets.token_urlsafe(32)
    await conn.execute("UPDATE users SET tickets = tickets - 1 WHERE user_id=$1", user_id)
    await conn.execute("""
        INSERT INTO ticket_games (user_id, game_type, session_token, game_data)
        VALUES ($1, $2, $3, $4)
    """, user_id, game_type, token, json.dumps(game_data))
    await conn.execute("""
        INSERT INTO ticket_transactions (user_id, amount, source, metadata)
        VALUES ($1, -1, 'ticket_game', $2)
    """, user_id, json.dumps({"game": game_type}))
    return token


async def _get_active_game(user_id: int, token: str, game_type: str, expiry_min: int, conn):
    row = await conn.fetchrow("""
        SELECT id, game_data FROM ticket_games
        WHERE session_token=$1 AND user_id=$2 AND game_type=$3 AND status='active'
          AND started_at > NOW() - ($4 * INTERVAL '1 minute')
        FOR UPDATE
    """, token, user_id, game_type, expiry_min)
    if not row:
        raise HTTPException(400, "Invalid or expired game session")
    return row


async def _complete_game(token: str, tickets_won: int, score: float, conn):
    await conn.execute("""
        UPDATE ticket_games
        SET status='completed', completed_at=NOW(), score=$1, tickets_won=$2
        WHERE session_token=$3
    """, score, tickets_won, token)
    if tickets_won > 0:
        uid = await conn.fetchval("SELECT user_id FROM ticket_games WHERE session_token=$1", token)
        await conn.execute("UPDATE users SET tickets = tickets + $1 WHERE user_id=$2", tickets_won, uid)
        await conn.execute("""
            INSERT INTO ticket_transactions (user_id, amount, source, metadata)
            VALUES ($1, $2, 'ticket_game_win', $3)
        """, uid, tickets_won, json.dumps({"score": score}))


# ── Reaction Time ──────────────────────────────────────────────

@router.post("/api/ticket-games/reaction/start")
async def reaction_start(request: Request):
    user_id = await require_auth(request)
    pool = await get_db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            token = await _start_game(user_id, "reaction", {}, conn)
    return {"token": token}


@router.post("/api/ticket-games/reaction/submit")
async def reaction_submit(request: Request):
    user_id = await require_auth(request)
    body = await request.json()
    token = str(body.get("token", ""))
    ms = float(body.get("ms", 9999))
    if ms < 100:   # anti-cheat floor — impossible to react faster
        ms = 9999
    tickets_won = next((r for t, r in REACTION_TIERS if ms < t), 0)
    pool = await get_db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _get_active_game(user_id, token, "reaction", 5, conn)
            await _complete_game(token, tickets_won, ms, conn)
    return {"tickets_won": tickets_won, "ms": round(ms)}


# ── Aim Trainer ────────────────────────────────────────────────

@router.post("/api/ticket-games/aim/start")
async def aim_start(request: Request):
    user_id = await require_auth(request)
    targets = [{"x": random.randint(5, 92), "y": random.randint(5, 85), "r": random.randint(18, 40)} for _ in range(20)]
    pool = await get_db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            token = await _start_game(user_id, "aim", {"targets": targets}, conn)
    return {"token": token, "targets": targets}


@router.post("/api/ticket-games/aim/submit")
async def aim_submit(request: Request):
    user_id = await require_auth(request)
    body = await request.json()
    token = str(body.get("token", ""))
    hits = min(20, max(0, int(body.get("hits", 0))))
    tickets_won = next((r for t, r in AIM_TIERS if hits >= t), 0)
    pool = await get_db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _get_active_game(user_id, token, "aim", 10, conn)
            await _complete_game(token, tickets_won, float(hits), conn)
    return {"tickets_won": tickets_won, "hits": hits}


# ── Bomb Defuse ────────────────────────────────────────────────

@router.post("/api/ticket-games/bomb/start")
async def bomb_start(request: Request):
    user_id = await require_auth(request)
    safe = random.choice(WIRE_COLORS)
    pool = await get_db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            token = await _start_game(user_id, "bomb", {"safe_wire": safe}, conn)
    return {"token": token, "wires": WIRE_COLORS}


@router.post("/api/ticket-games/bomb/submit")
async def bomb_submit(request: Request):
    user_id = await require_auth(request)
    body = await request.json()
    token = str(body.get("token", ""))
    chosen = str(body.get("wire", ""))
    pool = await get_db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await _get_active_game(user_id, token, "bomb", 3, conn)
            safe = json.loads(row["game_data"])["safe_wire"]
            won = chosen == safe
            await _complete_game(token, 3 if won else 0, 1.0 if won else 0.0, conn)
    return {"tickets_won": 3 if won else 0, "won": won, "safe_wire": safe, "chose": chosen}


# ── Float Guesser ──────────────────────────────────────────────

@router.post("/api/ticket-games/float/start")
async def float_start(request: Request):
    user_id = await require_auth(request)
    skin = random.choice(SKINS_DATA)
    fmin = float(skin.get("floatTop", 0.06))
    fmax = float(skin.get("floatBottom", 0.80))
    if fmin >= fmax:
        fmin, fmax = 0.06, 0.80
    actual = round(random.uniform(fmin, fmax), 4)
    weapon = ITEM_ID_TO_DISPLAY_NAME.get(skin.get("itemId", ""), skin.get("weaponType", "Unknown"))
    pool = await get_db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            token = await _start_game(user_id, "float", {"actual": actual, "fmin": fmin, "fmax": fmax}, conn)
    return {
        "token":      token,
        "skin_name":  f"{weapon} | {skin.get('name', 'Unknown')}",
        "skin_image": skin.get("skinImage", ""),
        "float_min":  fmin,
        "float_max":  fmax,
    }


@router.post("/api/ticket-games/float/submit")
async def float_submit(request: Request):
    user_id = await require_auth(request)
    body = await request.json()
    token = str(body.get("token", ""))
    guess = float(body.get("guess", 0))
    pool = await get_db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await _get_active_game(user_id, token, "float", 5, conn)
            gd = json.loads(row["game_data"])
            actual = float(gd["actual"])
            diff = abs(guess - actual)
            tickets_won = next((r for t, r in FLOAT_TIERS if diff <= t), 0)
            await _complete_game(token, tickets_won, diff, conn)
    return {"tickets_won": tickets_won, "actual": actual, "guess": guess, "diff": round(diff, 4)}


# ── Memory Sequence ────────────────────────────────────────────

@router.post("/api/ticket-games/memory/start")
async def memory_start(request: Request):
    user_id = await require_auth(request)
    sequence = [random.randint(0, 15) for _ in range(10)]
    pool = await get_db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            token = await _start_game(user_id, "memory", {"sequence": sequence}, conn)
    return {"token": token, "sequence": sequence}   # client displays this; server validates submission


@router.post("/api/ticket-games/memory/submit")
async def memory_submit(request: Request):
    user_id = await require_auth(request)
    body = await request.json()
    token = str(body.get("token", ""))
    answered = list(body.get("sequence", []))
    pool = await get_db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await _get_active_game(user_id, token, "memory", 10, conn)
            seq = json.loads(row["game_data"])["sequence"]
            correct = 0
            for i, val in enumerate(answered):
                if i >= len(seq) or int(val) != seq[i]:
                    break
                correct += 1
            tickets_won = next((r for t, r in MEMORY_TIERS if correct >= t), 0)
            await _complete_game(token, tickets_won, float(correct), conn)
    return {"tickets_won": tickets_won, "correct": correct, "sequence": seq, "total": len(seq)}
