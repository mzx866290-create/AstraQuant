-- ============================================
-- ClickHouse bootstrap schema for the stock platform
-- Mutable market tables include correction metadata so reruns stay traceable
-- and can migrate to ReplacingMergeTree later without changing writers.
-- ============================================

CREATE TABLE IF NOT EXISTS stock_daily
(
    symbol         LowCardinality(String),
    name           LowCardinality(String),
    date           Date,
    open           Decimal(18, 4),
    high           Decimal(18, 4),
    low            Decimal(18, 4),
    close          Decimal(18, 4),
    volume         UInt64,
    turnover       Decimal(24, 4),
    change_pct     Decimal(10, 4),
    change         Decimal(10, 4),
    amplitude      Decimal(10, 4),
    turnover_rate  Decimal(10, 6),
    up_limit       Decimal(18, 4),
    down_limit     Decimal(18, 4),
    pe_ttm         Decimal(18, 4),
    total_mv       Decimal(24, 4),
    circ_mv        Decimal(24, 4),
    adjust_flag    Int8 DEFAULT 0,
    source         LowCardinality(String),
    record_version UInt64 DEFAULT toUInt64(toUnixTimestamp64Milli(now64(3))),
    updated_at     DateTime DEFAULT now(),
    etl_batch_id   String DEFAULT ''
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(date)
ORDER BY (symbol, date)
TTL date + INTERVAL 10 YEAR;

CREATE TABLE IF NOT EXISTS stock_minute
(
    symbol         LowCardinality(String),
    timestamp      DateTime,
    open           Decimal(18, 4),
    high           Decimal(18, 4),
    low            Decimal(18, 4),
    close          Decimal(18, 4),
    volume         UInt64,
    turnover       Decimal(24, 4),
    trade_status   LowCardinality(String) DEFAULT '',
    market         LowCardinality(String) DEFAULT '',
    record_version UInt64 DEFAULT toUInt64(toUnixTimestamp64Milli(now64(3))),
    updated_at     DateTime DEFAULT now(),
    etl_batch_id   String DEFAULT ''
)
ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (symbol, timestamp)
TTL timestamp + INTERVAL 30 DAY;

CREATE TABLE IF NOT EXISTS stock_weekly
(
    symbol         LowCardinality(String),
    week_start     Date,
    open           Decimal(18, 4),
    high           Decimal(18, 4),
    low            Decimal(18, 4),
    close          Decimal(18, 4),
    volume         UInt64,
    turnover       Decimal(24, 4),
    change_pct     Decimal(10, 4),
    amplitude      Decimal(10, 4),
    record_version UInt64 DEFAULT toUInt64(toUnixTimestamp64Milli(now64(3))),
    updated_at     DateTime DEFAULT now(),
    etl_batch_id   String DEFAULT ''
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(week_start)
ORDER BY (symbol, week_start);

CREATE TABLE IF NOT EXISTS stock_monthly
(
    symbol         LowCardinality(String),
    month_start    Date,
    open           Decimal(18, 4),
    high           Decimal(18, 4),
    low            Decimal(18, 4),
    close          Decimal(18, 4),
    volume         UInt64,
    turnover       Decimal(24, 4),
    change_pct     Decimal(10, 4),
    amplitude      Decimal(10, 4),
    record_version UInt64 DEFAULT toUInt64(toUnixTimestamp64Milli(now64(3))),
    updated_at     DateTime DEFAULT now(),
    etl_batch_id   String DEFAULT ''
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(month_start)
ORDER BY (symbol, month_start);

CREATE TABLE IF NOT EXISTS money_flow
(
    symbol           LowCardinality(String),
    date             Date,
    main_net_inflow  Decimal(24, 4),
    small_net_inflow Decimal(24, 4),
    mid_net_inflow   Decimal(24, 4),
    big_net_inflow   Decimal(24, 4),
    super_net_inflow Decimal(24, 4),
    main_pct         Decimal(10, 4),
    source           LowCardinality(String),
    record_version   UInt64 DEFAULT toUInt64(toUnixTimestamp64Milli(now64(3))),
    updated_at       DateTime DEFAULT now(),
    etl_batch_id     String DEFAULT ''
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(date)
ORDER BY (symbol, date)
TTL date + INTERVAL 3 YEAR;

CREATE TABLE IF NOT EXISTS north_bound_flow
(
    date       Date,
    symbol     LowCardinality(String),
    name       LowCardinality(String),
    hold_vol   UInt64,
    hold_mv    Decimal(24, 4),
    net_inflow Decimal(24, 4),
    source     LowCardinality(String)
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(date)
ORDER BY (date, symbol)
TTL date + INTERVAL 3 YEAR;

CREATE TABLE IF NOT EXISTS stock_quotes
(
    symbol         LowCardinality(String),
    price          Decimal(18, 4),
    bid            Decimal(18, 4),
    ask            Decimal(18, 4),
    bid_volume     UInt64,
    ask_volume     UInt64,
    volume         UInt64,
    turnover       Decimal(24, 4),
    change_pct     Decimal(10, 4),
    change         Decimal(10, 4),
    high           Decimal(18, 4),
    low            Decimal(18, 4),
    open_px        Decimal(18, 4),
    total_mv       Decimal(24, 4),
    circ_mv        Decimal(24, 4),
    pe_ttm         Decimal(18, 4),
    turnover_rate  Decimal(10, 6),
    up_limit       Decimal(18, 4),
    down_limit     Decimal(18, 4),
    timestamp      DateTime,
    updated_at     DateTime DEFAULT now(),
    record_version UInt64 DEFAULT toUInt64(toUnixTimestamp64Milli(now64(3))),
    etl_batch_id   String DEFAULT ''
)
ENGINE = ReplacingMergeTree(record_version)
ORDER BY symbol
TTL updated_at + INTERVAL 7 DAY;

CREATE TABLE IF NOT EXISTS technical_indicators
(
    symbol     LowCardinality(String),
    date       Date,
    indicator  LowCardinality(String),
    value      Float64,
    created_at DateTime DEFAULT now()
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(date)
ORDER BY (symbol, date, indicator)
TTL created_at + INTERVAL 90 DAY;

CREATE TABLE IF NOT EXISTS sector_performance
(
    date          Date,
    sector_name   LowCardinality(String),
    sector_code   LowCardinality(String),
    change_pct    Decimal(10, 4),
    leader_symbol LowCardinality(String),
    leader_name   LowCardinality(String),
    leader_change Decimal(10, 4),
    rise_count    UInt16,
    fall_count    UInt16,
    source        LowCardinality(String)
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(date)
ORDER BY (date, change_pct DESC)
TTL date + INTERVAL 1 YEAR;

ALTER TABLE IF EXISTS stock_daily
    ADD COLUMN IF NOT EXISTS record_version UInt64 DEFAULT toUInt64(toUnixTimestamp64Milli(now64(3)));
ALTER TABLE IF EXISTS stock_daily
    ADD COLUMN IF NOT EXISTS updated_at DateTime DEFAULT now();
ALTER TABLE IF EXISTS stock_daily
    ADD COLUMN IF NOT EXISTS etl_batch_id String DEFAULT '';

ALTER TABLE IF EXISTS stock_minute
    ADD COLUMN IF NOT EXISTS record_version UInt64 DEFAULT toUInt64(toUnixTimestamp64Milli(now64(3)));
ALTER TABLE IF EXISTS stock_minute
    ADD COLUMN IF NOT EXISTS updated_at DateTime DEFAULT now();
ALTER TABLE IF EXISTS stock_minute
    ADD COLUMN IF NOT EXISTS etl_batch_id String DEFAULT '';

ALTER TABLE IF EXISTS stock_weekly
    ADD COLUMN IF NOT EXISTS record_version UInt64 DEFAULT toUInt64(toUnixTimestamp64Milli(now64(3)));
ALTER TABLE IF EXISTS stock_weekly
    ADD COLUMN IF NOT EXISTS updated_at DateTime DEFAULT now();
ALTER TABLE IF EXISTS stock_weekly
    ADD COLUMN IF NOT EXISTS etl_batch_id String DEFAULT '';

ALTER TABLE IF EXISTS stock_monthly
    ADD COLUMN IF NOT EXISTS record_version UInt64 DEFAULT toUInt64(toUnixTimestamp64Milli(now64(3)));
ALTER TABLE IF EXISTS stock_monthly
    ADD COLUMN IF NOT EXISTS updated_at DateTime DEFAULT now();
ALTER TABLE IF EXISTS stock_monthly
    ADD COLUMN IF NOT EXISTS etl_batch_id String DEFAULT '';

ALTER TABLE IF EXISTS money_flow
    ADD COLUMN IF NOT EXISTS record_version UInt64 DEFAULT toUInt64(toUnixTimestamp64Milli(now64(3)));
ALTER TABLE IF EXISTS money_flow
    ADD COLUMN IF NOT EXISTS updated_at DateTime DEFAULT now();
ALTER TABLE IF EXISTS money_flow
    ADD COLUMN IF NOT EXISTS etl_batch_id String DEFAULT '';

ALTER TABLE IF EXISTS stock_quotes
    ADD COLUMN IF NOT EXISTS record_version UInt64 DEFAULT toUInt64(toUnixTimestamp64Milli(now64(3)));
ALTER TABLE IF EXISTS stock_quotes
    ADD COLUMN IF NOT EXISTS etl_batch_id String DEFAULT '';
