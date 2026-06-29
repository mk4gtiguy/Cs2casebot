import random
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request
from shared import get_db, require_auth, logger

router = APIRouter()


def _is_online(last_seen) -> bool:
    if not last_seen:
        return False
    ts = last_seen if last_seen.tzinfo else last_seen.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ts).total_seconds() < 300


def _avatar(row) -> str:
    if (row.get("primary_provider") or "discord") == "google":
        return row.get("google_avatar_url") or row.get("avatar_url") or ""
    return row.get("avatar_url") or ""


# ── List friends ───────────────────────────────────────────────

@router.get("/api/friends")
async def get_friends(request: Request):
    user_id = await require_auth(request)
    pool = await get_db()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT u.user_id, u.username, u.avatar_url, u.google_avatar_url,
                   u.primary_provider, u.last_seen, u.level, f.id AS friendship_id
            FROM friendships f
            JOIN users u ON u.user_id = CASE
                WHEN f.requester_id = $1 THEN f.addressee_id ELSE f.requester_id END
            WHERE (f.requester_id = $1 OR f.addressee_id = $1) AND f.status = 'accepted'
            ORDER BY u.username
        """, user_id)
        return {"friends": [{
            "user_id":       str(r["user_id"]),
            "username":      r["username"],
            "avatar_url":    _avatar(r),
            "online":        _is_online(r["last_seen"]),
            "level":         int(r["level"] or 1),
            "friendship_id": r["friendship_id"],
        } for r in rows]}


# ── Friend requests (in / out) ─────────────────────────────────

@router.get("/api/friends/requests")
async def get_friend_requests(request: Request):
    user_id = await require_auth(request)
    pool = await get_db()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT f.id, f.requester_id, f.addressee_id,
                   u.username, u.avatar_url, u.google_avatar_url, u.primary_provider
            FROM friendships f
            JOIN users u ON u.user_id = CASE
                WHEN f.requester_id = $1 THEN f.addressee_id ELSE f.requester_id END
            WHERE (f.requester_id = $1 OR f.addressee_id = $1) AND f.status = 'pending'
            ORDER BY f.created_at DESC
        """, user_id)
        incoming, outgoing = [], []
        for r in rows:
            entry = {
                "id":        r["id"],
                "user_id":   str(r["requester_id"] if r["addressee_id"] == user_id else r["addressee_id"]),
                "username":  r["username"],
                "avatar_url": _avatar(r),
            }
            (incoming if r["addressee_id"] == user_id else outgoing).append(entry)
        return {"incoming": incoming, "outgoing": outgoing}


# ── Pending PvP challenges directed at me ─────────────────────

@router.get("/api/friends/challenges")
async def get_challenges(request: Request):
    user_id = await require_auth(request)
    pool = await get_db()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT c.id, c.challenger_id, c.bet_tickets,
                   u.username, u.avatar_url, u.google_avatar_url, u.primary_provider
            FROM pvp_challenges c
            JOIN users u ON u.user_id = c.challenger_id
            WHERE c.challenged_id = $1 AND c.status = 'pending' AND c.expires_at > NOW()
            ORDER BY c.created_at DESC
        """, user_id)
        return {"challenges": [{
            "id":                r["id"],
            "challenger_id":     str(r["challenger_id"]),
            "challenger_name":   r["username"],
            "challenger_avatar": _avatar(r),
            "bet_tickets":       r["bet_tickets"],
        } for r in rows]}


# ── Send friend request (by username or numeric ID) ───────────

@router.post("/api/friends/request")
async def send_friend_request(request: Request):
    user_id = await require_auth(request)
    body = await request.json()
    query = str(body.get("username_or_id", "")).strip()
    if not query:
        raise HTTPException(400, "username_or_id required")

    pool = await get_db()
    async with pool.acquire() as conn:
        target = None
        if query.isdigit():
            target = await conn.fetchrow("SELECT user_id FROM users WHERE user_id=$1", int(query))
        if not target:
            target = await conn.fetchrow(
                "SELECT user_id FROM users WHERE lower(username)=lower($1)", query
            )
        if not target:
            raise HTTPException(404, "User not found")
        target_id = target["user_id"]
        if target_id == user_id:
            raise HTTPException(400, "Cannot add yourself")

        existing = await conn.fetchrow("""
            SELECT id, status FROM friendships
            WHERE (requester_id=$1 AND addressee_id=$2) OR (requester_id=$2 AND addressee_id=$1)
        """, user_id, target_id)
        if existing:
            if existing["status"] == "accepted":
                raise HTTPException(400, "Already friends")
            raise HTTPException(400, "Request already pending")

        await conn.execute("""
            INSERT INTO friendships (requester_id, addressee_id, status)
            VALUES ($1, $2, 'pending')
        """, user_id, target_id)
        username = await conn.fetchval("SELECT username FROM users WHERE user_id=$1", target_id)
        return {"success": True, "message": f"Friend request sent to {username}"}


# ── Accept / decline friend request ───────────────────────────

@router.post("/api/friends/accept/{request_id}")
async def accept_friend_request(request_id: int, request: Request):
    user_id = await require_auth(request)
    pool = await get_db()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM friendships WHERE id=$1 AND addressee_id=$2 AND status='pending'",
            request_id, user_id,
        )
        if not row:
            raise HTTPException(404, "Request not found")
        await conn.execute(
            "UPDATE friendships SET status='accepted', updated_at=NOW() WHERE id=$1", request_id
        )
        return {"success": True}


@router.post("/api/friends/decline/{request_id}")
async def decline_friend_request(request_id: int, request: Request):
    user_id = await require_auth(request)
    pool = await get_db()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM friendships WHERE id=$1 AND (requester_id=$2 OR addressee_id=$2)",
            request_id, user_id,
        )
        return {"success": True}


# ── Unfriend ───────────────────────────────────────────────────

@router.delete("/api/friends/{friend_id}")
async def remove_friend(friend_id: int, request: Request):
    user_id = await require_auth(request)
    pool = await get_db()
    async with pool.acquire() as conn:
        await conn.execute("""
            DELETE FROM friendships
            WHERE ((requester_id=$1 AND addressee_id=$2) OR (requester_id=$2 AND addressee_id=$1))
              AND status='accepted'
        """, user_id, friend_id)
        return {"success": True}


# ── View a friend's public profile ────────────────────────────

@router.get("/api/friends/{friend_id}/profile")
async def friend_public_profile(friend_id: int, request: Request):
    user_id = await require_auth(request)
    pool = await get_db()
    async with pool.acquire() as conn:
        ok = await conn.fetchrow("""
            SELECT id FROM friendships
            WHERE ((requester_id=$1 AND addressee_id=$2) OR (requester_id=$2 AND addressee_id=$1))
              AND status='accepted'
        """, user_id, friend_id)
        if not ok:
            raise HTTPException(403, "Not friends with this user")

        u = await conn.fetchrow("""
            SELECT u.user_id, u.username, u.avatar_url, u.google_avatar_url,
                   u.primary_provider, u.level, u.prestige, u.last_seen,
                   (SELECT COUNT(*) FROM inventory WHERE user_id=u.user_id AND sold=FALSE) AS item_count
            FROM users u WHERE u.user_id=$1
        """, friend_id)
        if not u:
            raise HTTPException(404, "User not found")

        drops = await conn.fetch("""
            SELECT item_name, rarity FROM inventory
            WHERE user_id=$1 AND sold=FALSE
            ORDER BY acquired_at DESC NULLS LAST LIMIT 5
        """, friend_id)

        return {
            "user_id":      str(u["user_id"]),
            "username":     u["username"],
            "avatar_url":   _avatar(u),
            "level":        int(u["level"] or 1),
            "prestige":     int(u["prestige"] or 0),
            "item_count":   int(u["item_count"] or 0),
            "online":       _is_online(u["last_seen"]),
            "recent_drops": [{"name": d["item_name"], "rarity": d["rarity"]} for d in drops],
        }


# ── Send PvP ticket challenge ──────────────────────────────────

@router.post("/api/friends/{friend_id}/challenge")
async def challenge_friend(friend_id: int, request: Request):
    user_id = await require_auth(request)
    body = await request.json()
    bet = max(1, min(10, int(body.get("bet_tickets", 1))))

    pool = await get_db()
    async with pool.acquire() as conn:
        ok = await conn.fetchrow("""
            SELECT id FROM friendships
            WHERE ((requester_id=$1 AND addressee_id=$2) OR (requester_id=$2 AND addressee_id=$1))
              AND status='accepted'
        """, user_id, friend_id)
        if not ok:
            raise HTTPException(403, "Not friends with this user")

        async with conn.transaction():
            tix = await conn.fetchval("SELECT tickets FROM users WHERE user_id=$1 FOR UPDATE", user_id)
            if (tix or 0) < bet:
                raise HTTPException(400, "Not enough tickets")
            dup = await conn.fetchrow("""
                SELECT id FROM pvp_challenges
                WHERE challenger_id=$1 AND challenged_id=$2
                  AND status='pending' AND expires_at > NOW()
            """, user_id, friend_id)
            if dup:
                raise HTTPException(400, "You already have a pending challenge to this player")

            await conn.execute("UPDATE users SET tickets = tickets - $1 WHERE user_id=$2", bet, user_id)
            cid = await conn.fetchval("""
                INSERT INTO pvp_challenges (challenger_id, challenged_id, bet_tickets)
                VALUES ($1, $2, $3) RETURNING id
            """, user_id, friend_id, bet)
        return {"success": True, "challenge_id": cid}


# ── Accept / decline PvP challenge ────────────────────────────

@router.post("/api/friends/challenges/{challenge_id}/accept")
async def accept_challenge(challenge_id: int, request: Request):
    user_id = await require_auth(request)
    pool = await get_db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            ch = await conn.fetchrow("""
                SELECT * FROM pvp_challenges
                WHERE id=$1 AND challenged_id=$2 AND status='pending' AND expires_at > NOW()
                FOR UPDATE
            """, challenge_id, user_id)
            if not ch:
                raise HTTPException(404, "Challenge not found or expired")
            bet = ch["bet_tickets"]
            tix = await conn.fetchval("SELECT tickets FROM users WHERE user_id=$1 FOR UPDATE", user_id)
            if (tix or 0) < bet:
                raise HTTPException(400, "Not enough tickets")

            await conn.execute("UPDATE users SET tickets = tickets - $1 WHERE user_id=$2", bet, user_id)
            winner_id = ch["challenger_id"] if random.random() < 0.5 else user_id
            await conn.execute("UPDATE users SET tickets = tickets + $1 WHERE user_id=$2", bet * 2, winner_id)
            await conn.execute("""
                UPDATE pvp_challenges SET status='completed', winner_id=$1, completed_at=NOW()
                WHERE id=$2
            """, winner_id, challenge_id)

        return {
            "success":     True,
            "winner_id":   str(winner_id),
            "you_won":     winner_id == user_id,
            "tickets_won": bet * 2 if winner_id == user_id else 0,
        }


@router.post("/api/friends/challenges/{challenge_id}/decline")
async def decline_challenge(challenge_id: int, request: Request):
    user_id = await require_auth(request)
    pool = await get_db()
    async with pool.acquire() as conn:
        ch = await conn.fetchrow(
            "SELECT * FROM pvp_challenges WHERE id=$1 AND challenged_id=$2 AND status='pending'",
            challenge_id, user_id,
        )
        if not ch:
            raise HTTPException(404, "Challenge not found")
        async with conn.transaction():
            await conn.execute(
                "UPDATE users SET tickets = tickets + $1 WHERE user_id=$2",
                ch["bet_tickets"], ch["challenger_id"],
            )
            await conn.execute("UPDATE pvp_challenges SET status='declined' WHERE id=$1", challenge_id)
        return {"success": True}
