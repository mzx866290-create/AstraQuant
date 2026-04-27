-- ============================================
-- ClickHouse 初始化脚本 v2
-- A股时序行情数据表 (含A股特有字段)
-- ============================================

-- 日K线数据表（按月分区，symbol排序）
-- 包含A股全部核心字段
CREATE TABLE IF NOT EXISTS stock_daily
(
    symbol        LowCardinality(String),       -- 股票代码: 600519
    name          LowCardinality(String),        -- 股票名称
    date          Date,
    open          Decimal(18, 4),
    high          Decimal(18, 4),
    low           Decimal(18, 4),
    close         Decimal(18, 4),
    volume        UInt64,                        -- 成交量(股)
    turnover      Decimal(24, 4),                -- 成交额(元)
    change_pct    Decimal(10, 4),                -- 涨跌幅(%)
    change        Decimal(10, 4),                -- 涨跌额
    amplitude     Decimal(10, 4),                -- 振幅(%)
    turnover_rate Decimal(10, 6),                -- 换手率(%)
    -- A股特有字段
    up_limit      Decimal(18, 4),                -- 涨停价
    down_limit    Decimal(18, 4),                -- 跌停价
    pe_ttm        Decimal(18, 4),                -- 滚动市盈率
    total_mv      Decimal(24, 4),                -- 总市值
    circ_mv       Decimal(24, 4),                -- 流通市值
    adjust_flag   Int8 DEFAULT 0,                -- 复权标记: 0=未复权 1=前复权 2=后复权
    source        LowCardinality(String)         -- 数据来源
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(date)
ORDER BY (symbol, date)
TTL date + INTERVAL 10 YEAR;

-- 分钟级行情表（按天分区，7天TTL自动清理）
CREATE TABLE IF NOT EXISTS stock_minute
(
    symbol    LowCardinality(String),
    timestamp DateTime,
    open      Decimal(18, 4),
    high      Decimal(18, 4),
    low       Decimal(18, 4),
    close     Decimal(18, 4),
    volume    UInt64,
    turnover  Decimal(24, 4),                    -- 成交额
    -- 分钟级特有
    trade_status LowCardinality(String) DEFAULT '', -- 交易状态: C=集合竞价 T=连续竞价
    market       LowCardinality(String) DEFAULT ''  -- 市场: SH/SZ/BJ
)
ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (symbol, timestamp)
TTL timestamp + INTERVAL 30 DAY;

-- 周K线物化视图
CREATE TABLE IF NOT EXISTS stock_weekly
(
    symbol        LowCardinality(String),
    week_start    Date,
    open          Decimal(18, 4),
    high          Decimal(18, 4),
    low           Decimal(18, 4),
    close         Decimal(18, 4),
    volume        UInt64,
    turnover      Decimal(24, 4),
    change_pct    Decimal(10, 4),
    amplitude     Decimal(10, 4)
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(week_start)
ORDER BY (symbol, week_start);

-- 月K线物化视图
CREATE TABLE IF NOT EXISTS stock_monthly
(
    symbol        LowCardinality(String),
    month_start   Date,
    open          Decimal(18, 4),
    high          Decimal(18, 4),
    low           Decimal(18, 4),
    close         Decimal(18, 4),
    volume        UInt64,
    turnover      Decimal(24, 4),
    change_pct    Decimal(10, 4),
    amplitude     Decimal(10, 4)
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(month_start)
ORDER BY (symbol, month_start);

-- ============================================
-- A股特色数据表
-- ============================================

-- 资金流向表 (东方财富特色)
CREATE TABLE IF NOT EXISTS money_flow
(
    symbol        LowCardinality(String),
    date          Date,
    main_net_inflow  Decimal(24, 4),             -- 主力净流入额
    small_net_inflow Decimal(24, 4),             -- 小单净流入
    mid_net_inflow   Decimal(24, 4),             -- 中单净流入
    big_net_inflow   Decimal(24, 4),             -- 大单净流入
    super_net_inflow Decimal(24, 4),             -- 超大单净流入
    main_pct         Decimal(10, 4),             -- 主力净占比(%)
    source           LowCardinality(String)
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(date)
ORDER BY (symbol, date)
TTL date + INTERVAL 3 YEAR;

-- 龙虎榜数据
CREATE TABLE IF NOT EXISTS dragon_tiger
(
    trade_date    Date,
    symbol        LowCardinality(String),
    name          LowCardinality(String),
    reason        String,                        -- 上榜原因
    close_price   Decimal(18, 4),
    change_pct    Decimal(10, 4),
    turnover      Decimal(24, 4),                -- 龙虎榜成交额
    buy_amount    Decimal(24, 4),                -- 买入额
    sell_amount   Decimal(24, 4),                -- 卖出额
    net_amount    Decimal(24, 4),                -- 净额
    buy_seats     String,                        -- 买入席位(JSON)
    sell_seats    String,                        -- 卖出席位(JSON)
    source        LowCardinality(String)
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(trade_date)
ORDER BY (trade_date, symbol)
TTL trade_date + INTERVAL 1 YEAR;

-- 北向资金持仓数据
CREATE TABLE IF NOT EXISTS north_bound_flow
(
    date          Date,
    symbol        LowCardinality(String),
    name          LowCardinality(String),
    hold_vol      UInt64,                        -- 持仓数量
    hold_mv       Decimal(24, 4),                -- 持仓市值
    net_inflow    Decimal(24, 4),                -- 净流入
    source        LowCardinality(String)
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(date)
ORDER BY (date, symbol)
TTL date + INTERVAL 3 YEAR;

-- 实时行情快照表（最新报价，ReplacingMergeTree去重）
CREATE TABLE IF NOT EXISTS stock_quotes
(
    symbol       LowCardinality(String),
    price        Decimal(18, 4),
    bid          Decimal(18, 4),
    ask          Decimal(18, 4),
    bid_volume   UInt64,
    ask_volume   UInt64,
    volume       UInt64,
    turnover     Decimal(24, 4),
    change_pct   Decimal(10, 4),
    change       Decimal(10, 4),
    high         Decimal(18, 4),
    low          Decimal(18, 4),
    open_px      Decimal(18, 4),
    total_mv     Decimal(24, 4),
    circ_mv      Decimal(24, 4),
    pe_ttm       Decimal(18, 4),
    turnover_rate Decimal(10, 6),
    up_limit     Decimal(18, 4),
    down_limit   Decimal(18, 4),
    timestamp    DateTime,
    updated_at   DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY symbol
TTL updated_at + INTERVAL 7 DAY;

-- 技术指标缓存表
CREATE TABLE IF NOT EXISTS technical_indicators
(
    symbol       LowCardinality(String),
    date         Date,
    indicator    LowCardinality(String),         -- ma5, ma20, macd, boll...
    value        Float64,
    created_at   DateTime DEFAULT now()
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(date)
ORDER BY (symbol, date, indicator)
TTL created_at + INTERVAL 90 DAY;

-- 板块涨跌幅统计表
CREATE TABLE IF NOT EXISTS sector_performance
(
    date          Date,
    sector_name   LowCardinality(String),        -- 板块名称
    sector_code   LowCardinality(String),        -- 板块代码
    change_pct    Decimal(10, 4),                -- 板块涨跌幅
    leader_symbol LowCardinality(String),        -- 领涨股代码
    leader_name   LowCardinality(String),        -- 领涨股名称
    leader_change Decimal(10, 4),                -- 领涨股涨幅
    rise_count    UInt16,                        -- 上涨家数
    fall_count    UInt16,                        -- 下跌家数
    source        LowCardinality(String)
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(date)
ORDER BY (date, change_pct DESC)
TTL date + INTERVAL 1 YEAR;
