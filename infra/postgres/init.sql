-- ============================================
-- PostgreSQL 初始化脚本
-- 创建核心业务表
-- ============================================

-- 用户表
CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    username      VARCHAR(50)  UNIQUE NOT NULL,
    email         VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    nickname      VARCHAR(100),
    avatar_url    VARCHAR(500),
    role          VARCHAR(20)  DEFAULT 'free',
    is_active     BOOLEAN      DEFAULT TRUE,
    created_at    TIMESTAMPTZ  DEFAULT NOW(),
    updated_at    TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX idx_users_username ON users(username);
CREATE INDEX idx_users_created_at ON users(created_at DESC);

-- 股票基础信息表
CREATE TABLE IF NOT EXISTS stocks (
    id          SERIAL PRIMARY KEY,
    symbol      VARCHAR(20) UNIQUE NOT NULL,
    name        VARCHAR(100) NOT NULL,
    market      VARCHAR(10)  NOT NULL,
    sector      VARCHAR(100),
    list_date   DATE,
    is_active   BOOLEAN DEFAULT TRUE,
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_stocks_market ON stocks(market);
CREATE INDEX idx_stocks_symbol ON stocks(symbol);

-- 自选股分组表
CREATE TABLE IF NOT EXISTS watchlists (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name       VARCHAR(50) NOT NULL DEFAULT '默认分组',
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, name)
);

-- 自选股项目表
CREATE TABLE IF NOT EXISTS watchlist_items (
    id           SERIAL PRIMARY KEY,
    watchlist_id INTEGER NOT NULL REFERENCES watchlists(id) ON DELETE CASCADE,
    stock_id     INTEGER NOT NULL REFERENCES stocks(id),
    sort_order   INTEGER DEFAULT 0,
    added_at     TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(watchlist_id, stock_id)
);

-- 价格预警规则表
CREATE TABLE IF NOT EXISTS price_alerts (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    stock_id    INTEGER NOT NULL REFERENCES stocks(id),
    alert_type  VARCHAR(20) NOT NULL,
    threshold   DECIMAL(18,4) NOT NULL,
    is_active   BOOLEAN DEFAULT TRUE,
    triggered_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_alerts_user_active ON price_alerts(user_id, is_active);

-- 用户活动日志表
CREATE TABLE IF NOT EXISTS user_activity_logs (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER REFERENCES users(id),
    action     VARCHAR(50) NOT NULL,
    target     VARCHAR(100),
    ip_address INET,
    user_agent TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_activity_user_time ON user_activity_logs(user_id, created_at DESC);
CREATE INDEX idx_activity_action ON user_activity_logs(action);

-- AI 模型配置表
CREATE TABLE IF NOT EXISTS ai_models (
    id                SERIAL PRIMARY KEY,
    name              VARCHAR(100) NOT NULL,
    provider          VARCHAR(50)  NOT NULL,
    model_id          VARCHAR(100) NOT NULL,
    api_base_url      VARCHAR(500),
    api_key_encrypted TEXT NOT NULL,
    description       TEXT,
    config            JSONB,
    is_active         BOOLEAN DEFAULT TRUE,
    sort_order        INTEGER DEFAULT 0,
    allowed_roles     VARCHAR(100) DEFAULT 'free,premium,admin',
    created_by        INTEGER REFERENCES users(id),
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    updated_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_ai_models_provider ON ai_models(provider);
CREATE INDEX idx_ai_models_active ON ai_models(is_active);

-- AI 模型调用日志表
CREATE TABLE IF NOT EXISTS ai_usage_logs (
    id                SERIAL PRIMARY KEY,
    user_id           INTEGER NOT NULL REFERENCES users(id),
    model_id          INTEGER NOT NULL REFERENCES ai_models(id),
    stock_symbol      VARCHAR(20),
    prompt_tokens     INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    total_tokens      INTEGER DEFAULT 0,
    cost              DECIMAL(10,6) DEFAULT 0,
    status            VARCHAR(20) DEFAULT 'success',
    error_message     TEXT,
    response_time_ms  INTEGER DEFAULT 0,
    created_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_usage_user ON ai_usage_logs(user_id);
CREATE INDEX idx_usage_model ON ai_usage_logs(model_id);
CREATE INDEX idx_usage_created ON ai_usage_logs(created_at DESC);
CREATE INDEX idx_usage_status ON ai_usage_logs(status);

-- 用户配额表
CREATE TABLE IF NOT EXISTS user_quotas (
    id                  SERIAL PRIMARY KEY,
    user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    daily_limit         INTEGER DEFAULT 10,
    monthly_limit       INTEGER DEFAULT 100,
    daily_used          INTEGER DEFAULT 0,
    monthly_used        INTEGER DEFAULT 0,
    last_reset_daily    TIMESTAMPTZ DEFAULT NOW(),
    last_reset_monthly  TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id)
);

CREATE INDEX idx_quota_user ON user_quotas(user_id);

-- 研究观察快照表
CREATE TABLE IF NOT EXISTS research_observations (
    id                   SERIAL PRIMARY KEY,
    snapshot_date        TIMESTAMPTZ NOT NULL,
    symbol               VARCHAR(20) NOT NULL,
    strategy_id          VARCHAR(50) NOT NULL,
    regime               VARCHAR(30) NOT NULL,
    score                DOUBLE PRECISION NOT NULL,
    score_breakdown_json JSONB,
    evidence_chain_json  JSONB,
    debate_json          JSONB,
    veto_result_json     JSONB,
    close_price          DOUBLE PRECISION,
    created_at           TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(snapshot_date, symbol, strategy_id)
);

CREATE INDEX idx_research_observations_snapshot_date ON research_observations(snapshot_date DESC);
CREATE INDEX idx_research_observations_symbol ON research_observations(symbol);
CREATE INDEX idx_research_observations_strategy_id ON research_observations(strategy_id);
CREATE INDEX idx_research_observations_regime ON research_observations(regime);

-- 研究观察复盘表
CREATE TABLE IF NOT EXISTS observation_reviews (
    id                      SERIAL PRIMARY KEY,
    observation_id          INTEGER NOT NULL REFERENCES research_observations(id) ON DELETE CASCADE,
    review_offset           VARCHAR(10) NOT NULL,
    review_date             TIMESTAMPTZ NOT NULL,
    close_price             DOUBLE PRECISION,
    return_pct              DOUBLE PRECISION,
    max_drawdown_pct        DOUBLE PRECISION,
    falsification_triggered BOOLEAN DEFAULT FALSE,
    risk_signal_valid       BOOLEAN DEFAULT FALSE,
    notes                   TEXT,
    created_at              TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(observation_id, review_offset)
);

CREATE INDEX idx_observation_reviews_observation_id ON observation_reviews(observation_id);
CREATE INDEX idx_observation_reviews_review_date ON observation_reviews(review_date DESC);
CREATE INDEX idx_observation_reviews_review_offset ON observation_reviews(review_offset);

-- Weight suggestion audit trail
CREATE TABLE IF NOT EXISTS weight_suggestion_audits (
    id               SERIAL PRIMARY KEY,
    generated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    snapshot_from    TIMESTAMPTZ,
    snapshot_to      TIMESTAMPTZ,
    min_reviews      INTEGER NOT NULL,
    status           VARCHAR(30) NOT NULL,
    suggestions_json JSONB,
    summary_json     JSONB,
    accepted         BOOLEAN,
    accepted_by      INTEGER,
    accepted_at      TIMESTAMPTZ,
    notes            TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_weight_suggestion_audits_generated_at ON weight_suggestion_audits(generated_at DESC);

-- Strategy weight patch proposals generated from accepted audits
CREATE TABLE IF NOT EXISTS strategy_weight_patch_proposals (
    id            SERIAL PRIMARY KEY,
    audit_id      INTEGER NOT NULL REFERENCES weight_suggestion_audits(id) ON DELETE CASCADE,
    strategy_id   VARCHAR(50) NOT NULL,
    status        VARCHAR(20) NOT NULL DEFAULT 'pending',
    step          DOUBLE PRECISION NOT NULL,
    max_delta     DOUBLE PRECISION NOT NULL,
    before_json   JSONB,
    after_json    JSONB,
    delta_json    JSONB,
    items_json    JSONB,
    preview_json  JSONB,
    created_by    INTEGER,
    decided_by    INTEGER,
    decided_at    TIMESTAMPTZ,
    applied_by    INTEGER,
    applied_at    TIMESTAMPTZ,
    applied_error TEXT,
    notes         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_strategy_weight_patch_proposals_audit_id ON strategy_weight_patch_proposals(audit_id);
CREATE INDEX idx_strategy_weight_patch_proposals_strategy_id ON strategy_weight_patch_proposals(strategy_id);
CREATE INDEX idx_strategy_weight_patch_proposals_status ON strategy_weight_patch_proposals(status);
CREATE INDEX idx_strategy_weight_patch_proposals_created_at ON strategy_weight_patch_proposals(created_at DESC);

-- Applied strategy weight config versions for rollback
CREATE TABLE IF NOT EXISTS strategy_weight_versions (
    id              SERIAL PRIMARY KEY,
    strategy_id     VARCHAR(50) NOT NULL,
    proposal_id     INTEGER REFERENCES strategy_weight_patch_proposals(id) ON DELETE SET NULL,
    version         INTEGER NOT NULL,
    before_json     JSONB,
    after_json      JSONB,
    applied_by      INTEGER,
    applied_at      TIMESTAMPTZ,
    rolled_back_by  INTEGER,
    rolled_back_at  TIMESTAMPTZ,
    rollback_error  TEXT,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_strategy_weight_versions_strategy_id ON strategy_weight_versions(strategy_id);
CREATE INDEX idx_strategy_weight_versions_proposal_id ON strategy_weight_versions(proposal_id);
CREATE INDEX idx_strategy_weight_versions_version ON strategy_weight_versions(version);
CREATE INDEX idx_strategy_weight_versions_created_at ON strategy_weight_versions(created_at DESC);

-- 初始化样本股票数据
INSERT INTO stocks (symbol, name, market, sector) VALUES
    ('600519.SS', '贵州茅台', 'SH', '食品饮料'),
    ('000858.SZ', '五粮液', 'SZ', '食品饮料'),
    ('000651.SZ', '格力电器', 'SZ', '家电'),
    ('600036.SS', '招商银行', 'SH', '银行'),
    ('601398.SS', '工商银行', 'SH', '银行'),
    ('000333.SZ', '美的集团', 'SZ', '家电'),
    ('601888.SS', '中国国旅', 'SH', '旅游'),
    ('603259.SS', '药明康德', 'SH', '医药')
ON CONFLICT DO NOTHING;

-- 管理员账号不再使用固定默认密码初始化。
-- 如需首个管理员，请通过显式的 bootstrap 脚本或 BOOTSTRAP_ADMIN_PASSWORD 创建。
