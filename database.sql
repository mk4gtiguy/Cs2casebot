DROP TABLE IF EXISTS giveaway_entries CASCADE;
DROP TABLE IF EXISTS giveaways CASCADE;
DROP TABLE IF EXISTS quests CASCADE;
DROP TABLE IF EXISTS inventory CASCADE;
DROP TABLE IF EXISTS users CASCADE;
DROP TABLE IF EXISTS auth_methods CASCADE;
DROP TABLE IF EXISTS guild_memberships CASCADE;
DROP TABLE IF EXISTS guild_settings CASCADE;
DROP TABLE IF EXISTS premium_openings CASCADE;
DROP TABLE IF EXISTS ticket_purchases CASCADE;

CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    user_id BIGINT UNIQUE,
    username VARCHAR(100),
    email VARCHAR(255),
    balance DECIMAL(15,2) DEFAULT 1000,
    credits INTEGER DEFAULT 0,
    total_opens INTEGER DEFAULT 0,
    total_premium_opens INTEGER DEFAULT 0,
    total_golds INTEGER DEFAULT 0,
    total_trades INTEGER DEFAULT 0,
    daily_streak INTEGER DEFAULT 0,
    last_daily TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE auth_methods (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    provider VARCHAR(20) NOT NULL,
    provider_user_id VARCHAR(255) NOT NULL,
    provider_username VARCHAR(100),
    provider_email VARCHAR(255),
    avatar_url TEXT,
    is_primary BOOLEAN DEFAULT FALSE,
    linked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(provider, provider_user_id)
);

CREATE TABLE guild_memberships (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    guild_id BIGINT NOT NULL,
    guild_name VARCHAR(100),
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, guild_id)
);

CREATE TABLE guild_settings (
    guild_id BIGINT PRIMARY KEY,
    name VARCHAR(100),
    prefix VARCHAR(10) DEFAULT '!',
    daily_reward_min INTEGER DEFAULT 500,
    daily_reward_max INTEGER DEFAULT 1500,
    case_channel_id BIGINT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE inventory (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    item_name TEXT NOT NULL,
    item_type TEXT DEFAULT 'weapon',
    rarity TEXT NOT NULL,
    price DECIMAL(10,2) NOT NULL,
    quality TEXT,
    is_stattrak BOOLEAN DEFAULT FALSE,
    status TEXT DEFAULT 'kept',
    case_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE premium_openings (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    case_id VARCHAR(50) NOT NULL,
    item_id INTEGER REFERENCES inventory(id),
    ticket_cost INTEGER NOT NULL,
    opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE ticket_purchases (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    amount INTEGER NOT NULL,
    cost_usd DECIMAL(10,2) NOT NULL,
    stripe_session_id VARCHAR(255),
    purchased_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE quests (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    quest_type VARCHAR(30),
    progress INT DEFAULT 0,
    required INT,
    completed BOOLEAN DEFAULT FALSE,
    claimed BOOLEAN DEFAULT FALSE,
    reward INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE giveaways (
    id SERIAL PRIMARY KEY,
    message_id BIGINT,
    channel_id BIGINT,
    prize VARCHAR(100),
    winner_count INT,
    ended BOOLEAN DEFAULT FALSE,
    end_time TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE giveaway_entries (
    id SERIAL PRIMARY KEY,
    giveaway_id INT REFERENCES giveaways(id),
    user_id BIGINT
);

CREATE INDEX idx_auth_methods_provider ON auth_methods(provider, provider_user_id);
CREATE INDEX idx_guild_memberships_user ON guild_memberships(user_id);
CREATE INDEX idx_inventory_user ON inventory(user_id);

INSERT INTO guild_settings (guild_id, name, is_active) 
VALUES (1515565362408853596, 'CS2CaseBot Official', TRUE)
ON CONFLICT (guild_id) DO NOTHING;