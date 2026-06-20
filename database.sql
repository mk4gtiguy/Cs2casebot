-- ============================================
-- CS2CaseBot - CORRECT DATABASE SCHEMA
-- MATCHES main.py AND web_server.py
-- ============================================

-- ============================================
-- DROP ALL TABLES IN CORRECT ORDER
-- ============================================

DROP TABLE IF EXISTS giveaway_entries CASCADE;
DROP TABLE IF EXISTS giveaways CASCADE;
DROP TABLE IF EXISTS coinflip_games CASCADE;
DROP TABLE IF EXISTS dice_games CASCADE;
DROP TABLE IF EXISTS mines_games CASCADE;
DROP TABLE IF EXISTS slots_games CASCADE;
DROP TABLE IF EXISTS user_achievements CASCADE;
DROP TABLE IF EXISTS user_streaks CASCADE;
DROP TABLE IF EXISTS user_settings CASCADE;
DROP TABLE IF EXISTS live_feed CASCADE;
DROP TABLE IF EXISTS skin_upgrades CASCADE;
DROP TABLE IF EXISTS ticket_purchases CASCADE;
DROP TABLE IF EXISTS donations CASCADE;
DROP TABLE IF EXISTS guild_memberships CASCADE;
DROP TABLE IF EXISTS guild_settings CASCADE;
DROP TABLE IF EXISTS inventory CASCADE;
DROP TABLE IF EXISTS quests CASCADE;
DROP TABLE IF EXISTS auth_methods CASCADE;
DROP TABLE IF EXISTS users CASCADE;

-- ============================================
-- USERS TABLE - PRIMARY KEY IS user_id (Discord ID)
-- ============================================

CREATE TABLE users (
    user_id BIGINT PRIMARY KEY,  -- Discord/Google ID is the PRIMARY KEY
    username TEXT,
    email TEXT,
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
);

-- Indexes for performance
CREATE INDEX idx_users_balance ON users(balance DESC);
CREATE INDEX idx_users_total_opens ON users(total_opens DESC);
CREATE INDEX idx_users_total_golds ON users(total_golds DESC);
CREATE INDEX idx_users_total_trades ON users(total_trades DESC);
CREATE INDEX idx_users_created_at ON users(created_at DESC);

-- ============================================
-- AUTH METHODS - Links OAuth providers to user_id
-- ============================================

CREATE TABLE auth_methods (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    provider_user_id TEXT NOT NULL,
    provider_username TEXT,
    provider_email TEXT,
    avatar_url TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(provider, provider_user_id)
);

CREATE INDEX idx_auth_methods_user_id ON auth_methods(user_id);
CREATE INDEX idx_auth_methods_provider ON auth_methods(provider, provider_user_id);

-- ============================================
-- GUILD SETTINGS - Per-server bot settings
-- ============================================

CREATE TABLE guild_settings (
    guild_id BIGINT PRIMARY KEY,
    name TEXT,
    bot_channel_id BIGINT,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- ============================================
-- GUILD MEMBERSHIPS - Track which guilds users are in
-- ============================================

CREATE TABLE guild_memberships (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    guild_id BIGINT,
    guild_name TEXT,
    joined_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, guild_id)
);

CREATE INDEX idx_guild_memberships_user_id ON guild_memberships(user_id);
CREATE INDEX idx_guild_memberships_guild_id ON guild_memberships(guild_id);

-- ============================================
-- INVENTORY - User's items
-- ============================================

CREATE TABLE inventory (
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
);

CREATE INDEX idx_inventory_user_id ON inventory(user_id);
CREATE INDEX idx_inventory_status ON inventory(status);
CREATE INDEX idx_inventory_rarity ON inventory(rarity);
CREATE INDEX idx_inventory_created_at ON inventory(created_at DESC);

-- ============================================
-- QUESTS - Daily quests
-- ============================================

CREATE TABLE quests (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
    quest_type TEXT,
    progress INTEGER DEFAULT 0,
    required INTEGER,
    reward INTEGER,
    completed BOOLEAN DEFAULT FALSE,
    claimed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_quests_user_id ON quests(user_id);
CREATE INDEX idx_quests_claimed ON quests(claimed);
CREATE INDEX idx_quests_created_at ON quests(created_at);

-- ============================================
-- GIVEAWAYS
-- ============================================

CREATE TABLE giveaways (
    id SERIAL PRIMARY KEY,
    message_id BIGINT,
    channel_id BIGINT,
    prize TEXT,
    winner_count INTEGER DEFAULT 1,
    end_time TIMESTAMP,
    ended BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE giveaway_entries (
    id SERIAL PRIMARY KEY,
    giveaway_id INTEGER REFERENCES giveaways(id) ON DELETE CASCADE,
    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_giveaway_entries_giveaway_id ON giveaway_entries(giveaway_id);
CREATE INDEX idx_giveaway_entries_user_id ON giveaway_entries(user_id);

-- ============================================
-- GAME TABLES
-- ============================================

-- Coinflip games
CREATE TABLE coinflip_games (
    id SERIAL PRIMARY KEY,
    creator_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
    opponent_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
    amount DECIMAL(15,2),
    winner_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
    status TEXT DEFAULT 'waiting',
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

CREATE INDEX idx_coinflip_games_creator_id ON coinflip_games(creator_id);
CREATE INDEX idx_coinflip_games_status ON coinflip_games(status);
CREATE INDEX idx_coinflip_games_opponent_id ON coinflip_games(opponent_id);

-- Dice games
CREATE TABLE dice_games (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
    amount DECIMAL(15,2),
    bet_type TEXT,
    bet_number INTEGER,
    roll_number INTEGER,
    result TEXT,
    multiplier DECIMAL(10,2),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_dice_games_user_id ON dice_games(user_id);

-- Mines games
CREATE TABLE mines_games (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
    bet_amount DECIMAL(15,2),
    grid_size INTEGER DEFAULT 5,
    mine_count INTEGER DEFAULT 3,
    status TEXT DEFAULT 'active',
    mine_positions INTEGER[],
    revealed_tiles INTEGER[] DEFAULT '{}',
    multiplier DECIMAL(10,2) DEFAULT 1.0,
    win_amount DECIMAL(15,2),
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_mines_games_user_id ON mines_games(user_id);
CREATE INDEX idx_mines_games_status ON mines_games(status);

-- Slots games
CREATE TABLE slots_games (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
    bet_amount DECIMAL(15,2),
    spin_result TEXT[],
    multiplier DECIMAL(10,2),
    win_amount DECIMAL(15,2),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_slots_games_user_id ON slots_games(user_id);

-- ============================================
-- USER ACHIEVEMENTS
-- ============================================

CREATE TABLE user_achievements (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
    achievement_id TEXT,
    unlocked_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_user_achievements_user_id ON user_achievements(user_id);
CREATE INDEX idx_user_achievements_achievement_id ON user_achievements(achievement_id);

-- ============================================
-- USER STREAKS
-- ============================================

CREATE TABLE user_streaks (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
    current_streak INTEGER DEFAULT 0,
    best_streak INTEGER DEFAULT 0,
    golds_in_streak INTEGER DEFAULT 0,
    total_session_opens INTEGER DEFAULT 0,
    current_case_id TEXT,
    updated_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_user_streaks_user_id ON user_streaks(user_id);

-- ============================================
-- USER SETTINGS
-- ============================================

CREATE TABLE user_settings (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
    theme TEXT DEFAULT 'casino',
    spin_speed TEXT DEFAULT 'normal',
    sound_enabled BOOLEAN DEFAULT TRUE,
    feed_enabled BOOLEAN DEFAULT TRUE,
    confetti_mode TEXT DEFAULT 'always',
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_user_settings_user_id ON user_settings(user_id);

-- ============================================
-- LIVE FEED
-- ============================================

CREATE TABLE live_feed (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
    username TEXT,
    item_name TEXT NOT NULL,
    rarity TEXT,
    rarity_emoji TEXT,
    case_type TEXT DEFAULT 'regular',
    float_value DECIMAL(10,4),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_live_feed_created_at ON live_feed(created_at DESC);
CREATE INDEX idx_live_feed_user_id ON live_feed(user_id);

-- ============================================
-- DONATIONS
-- ============================================

CREATE TABLE donations (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
    amount DECIMAL(15,2),
    donor_name TEXT,
    donor_email TEXT,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- ============================================
-- TICKET PURCHASES
-- ============================================

CREATE TABLE ticket_purchases (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
    amount INTEGER,
    cost_usd DECIMAL(10,2),
    stripe_session_id TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ============================================
-- SKIN UPGRADES
-- ============================================

CREATE TABLE skin_upgrades (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
    item_id INTEGER,
    input_rarity TEXT,
    output_rarity TEXT,
    success BOOLEAN,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ============================================
-- TRIGGERS FOR UPDATED_AT
-- ============================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_users_updated_at
BEFORE UPDATE ON users
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_user_settings_updated_at
BEFORE UPDATE ON user_settings
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

-- ============================================
-- VERIFICATION QUERY
-- ============================================

-- Check all tables exist:
-- SELECT table_name FROM information_schema.tables 
-- WHERE table_schema = 'public' 
-- ORDER BY table_name;

-- Check users table columns:
-- SELECT column_name, data_type FROM information_schema.columns 
-- WHERE table_name = 'users' 
-- ORDER BY column_name;