-- Trading Factory PostgreSQL Schema
-- All 8 tables as specified in the handbook

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. strategies
CREATE TABLE IF NOT EXISTS strategies (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    strategy_code VARCHAR(32) UNIQUE NOT NULL,
    name VARCHAR(128) NOT NULL,
    style VARCHAR(32) NOT NULL,
    asset VARCHAR(8) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE',
    current_stage VARCHAR(24) NOT NULL DEFAULT 'IDEA',
    current_mode VARCHAR(16),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    retired_at TIMESTAMPTZ,
    consecutive_demotions INTEGER DEFAULT 0,
    current_rank INTEGER,
    is_active BOOLEAN DEFAULT TRUE,
    template_config JSONB
);

-- 2. strategy_metrics
CREATE TABLE IF NOT EXISTS strategy_metrics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    strategy_id UUID NOT NULL REFERENCES strategies(id) ON DELETE CASCADE,
    stage VARCHAR(24) NOT NULL,
    pnl DOUBLE PRECISION DEFAULT 0.0,
    sharpe DOUBLE PRECISION DEFAULT 0.0,
    drawdown DOUBLE PRECISION DEFAULT 0.0,
    win_rate DOUBLE PRECISION DEFAULT 0.0,
    trade_count INTEGER DEFAULT 0,
    expectancy DOUBLE PRECISION DEFAULT 0.0,
    profit_factor DOUBLE PRECISION DEFAULT 0.0,
    timestamp TIMESTAMPTZ DEFAULT NOW()
);

-- 3. strategy_history
CREATE TABLE IF NOT EXISTS strategy_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    strategy_id UUID NOT NULL REFERENCES strategies(id) ON DELETE CASCADE,
    event_type VARCHAR(32) NOT NULL,
    from_stage VARCHAR(24),
    to_stage VARCHAR(24),
    reason TEXT,
    actor VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 4. audit_log
CREATE TABLE IF NOT EXISTS audit_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    strategy_id UUID REFERENCES strategies(id) ON DELETE SET NULL,
    event_type VARCHAR(32) NOT NULL,
    source_service VARCHAR(64) NOT NULL,
    payload_json JSONB,
    success BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 5. trade_explanations
CREATE TABLE IF NOT EXISTS trade_explanations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    strategy_id UUID NOT NULL REFERENCES strategies(id) ON DELETE CASCADE,
    trade_id VARCHAR(64) NOT NULL,
    explanation_text TEXT NOT NULL,
    contributing_factors_json JSONB,
    result VARCHAR(16) NOT NULL,
    pnl DOUBLE PRECISION DEFAULT 0.0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 6. research_sources
CREATE TABLE IF NOT EXISTS research_sources (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    strategy_style VARCHAR(32) NOT NULL,
    trader_name VARCHAR(128) NOT NULL,
    market_focus VARCHAR(64) NOT NULL,
    activity_status VARCHAR(16) DEFAULT 'active',
    research_notes TEXT,
    extracted_patterns_json JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 7. strategy_research_links
CREATE TABLE IF NOT EXISTS strategy_research_links (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    strategy_id UUID NOT NULL REFERENCES strategies(id) ON DELETE CASCADE,
    research_source_id UUID NOT NULL REFERENCES research_sources(id) ON DELETE CASCADE,
    influence_weight DOUBLE PRECISION DEFAULT 1.0,
    notes TEXT
);

-- 8. overrides
CREATE TABLE IF NOT EXISTS overrides (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    strategy_id UUID REFERENCES strategies(id) ON DELETE SET NULL,
    requested_by VARCHAR(64) NOT NULL,
    approved_by VARCHAR(64),
    result VARCHAR(16) NOT NULL DEFAULT 'PENDING',
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_strategies_stage ON strategies(current_stage);
CREATE INDEX IF NOT EXISTS idx_strategies_status ON strategies(status);
CREATE INDEX IF NOT EXISTS idx_strategies_style ON strategies(style);
CREATE INDEX IF NOT EXISTS idx_strategy_metrics_sid ON strategy_metrics(strategy_id);
CREATE INDEX IF NOT EXISTS idx_strategy_metrics_ts ON strategy_metrics(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_strategy_history_sid ON strategy_history(strategy_id);
CREATE INDEX IF NOT EXISTS idx_strategy_history_ts ON strategy_history(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_type ON audit_log(event_type);
CREATE INDEX IF NOT EXISTS idx_audit_log_ts ON audit_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_sid ON audit_log(strategy_id);
CREATE INDEX IF NOT EXISTS idx_trade_explanations_sid ON trade_explanations(strategy_id);
CREATE INDEX IF NOT EXISTS idx_research_sources_style ON research_sources(strategy_style);
