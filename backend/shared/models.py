"""共享数据模型 - SQLAlchemy ORM 模型定义"""
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey, UniqueConstraint, JSON
from sqlalchemy.orm import declarative_base
from datetime import datetime, timezone

Base = declarative_base()


class Stock(Base):
    """股票基础信息表"""
    __tablename__ = "stocks"
    
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    market = Column(String(10), nullable=False, index=True)  # SH/SZ/HK/US
    sector = Column(String(100), nullable=True)
    list_date = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class User(Base):
    """用户表"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    nickname = Column(String(100), nullable=True)
    avatar_url = Column(String(500), nullable=True)
    role = Column(String(20), default="free")  # free/premium/admin
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class Watchlist(Base):
    """自选股分组表"""
    __tablename__ = "watchlists"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(50), nullable=False, default="默认分组")
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (UniqueConstraint("user_id", "name", name="uix_user_watchlist"),)


class WatchlistItem(Base):
    """自选股项目表"""
    __tablename__ = "watchlist_items"

    id = Column(Integer, primary_key=True, index=True)
    watchlist_id = Column(Integer, ForeignKey("watchlists.id", ondelete="CASCADE"), nullable=False, index=True)
    stock_id = Column(Integer, ForeignKey("stocks.id"), nullable=False, index=True)
    sort_order = Column(Integer, default=0)
    added_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (UniqueConstraint("watchlist_id", "stock_id", name="uix_watchlist_stock"),)


class PriceAlert(Base):
    """价格预警规则表"""
    __tablename__ = "price_alerts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    stock_id = Column(Integer, ForeignKey("stocks.id"), nullable=False, index=True)
    alert_type = Column(String(20), nullable=False)  # price_above/price_below/change_pct
    threshold = Column(Float, nullable=False)
    is_active = Column(Boolean, default=True)
    triggered_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class UserActivityLog(Base):
    """用户活动日志表"""
    __tablename__ = "user_activity_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    action = Column(String(50), nullable=False)
    target = Column(String(100), nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class PasswordResetToken(Base):
    """One-time password reset token. Only the token hash is stored."""
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    used_at = Column(DateTime, nullable=True)
    requested_ip = Column(String(45), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class AIModel(Base):
    """AI 模型配置表"""
    __tablename__ = "ai_models"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)                # 显示名称，如 "Claude 3.5 Sonnet"
    provider = Column(String(50), nullable=False)             # 提供商: openai / anthropic / deepseek / custom
    model_id = Column(String(100), nullable=False)            # 模型标识: gpt-4o / claude-sonnet-4-20250514 等
    api_base_url = Column(String(500), nullable=True)         # API 基础地址 (自定义时必填)
    api_key_encrypted = Column(Text, nullable=False)          # 加密后的 API Key
    description = Column(Text, nullable=True)                 # 模型描述
    config = Column(JSON, nullable=True)                      # 额外配置: {temperature, max_tokens, system_prompt 等}
    is_active = Column(Boolean, default=True)                 # 是否启用
    sort_order = Column(Integer, default=0)                   # 排序权重
    allowed_roles = Column(String(100), default="free,premium,admin")  # 允许使用的角色,逗号分隔
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class AIUsageLog(Base):
    """AI 模型调用日志表"""
    __tablename__ = "ai_usage_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    model_id = Column(Integer, ForeignKey("ai_models.id"), nullable=False, index=True)
    stock_symbol = Column(String(20), nullable=True)          # 分析的股票代码
    prompt_tokens = Column(Integer, default=0)                # 输入 token 数
    completion_tokens = Column(Integer, default=0)            # 输出 token 数
    total_tokens = Column(Integer, default=0)                 # 总 token 数
    cost = Column(Float, default=0.0)                         # 预估费用 (USD)
    status = Column(String(20), default="success")            # success / error / timeout
    error_message = Column(Text, nullable=True)               # 错误信息
    response_time_ms = Column(Integer, default=0)             # 响应时间(毫秒)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class UserQuota(Base):
    """用户配额表"""
    __tablename__ = "user_quotas"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    daily_limit = Column(Integer, default=10)                 # 每日调用上限
    monthly_limit = Column(Integer, default=100)              # 每月调用上限
    daily_used = Column(Integer, default=0)                   # 今日已用次数
    monthly_used = Column(Integer, default=0)                 # 本月已用次数
    last_reset_daily = Column(DateTime, default=lambda: datetime.now(timezone.utc))   # 上次每日重置时间
    last_reset_monthly = Column(DateTime, default=lambda: datetime.now(timezone.utc)) # 上次每月重置时间
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (UniqueConstraint("user_id", name="uix_user_quota"),)


class CompanyAnnouncement(Base):
    """公司公告表"""
    __tablename__ = "company_announcements"

    id = Column(Integer, primary_key=True, index=True)
    stock_symbol = Column(String(20), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    summary = Column(Text, nullable=True)
    content_url = Column(String(500), nullable=True)
    announce_date = Column(DateTime, nullable=False, index=True)
    source = Column(String(50), default="akshare")
    category = Column(String(50), nullable=True)  # 定期报告/临时公告/业绩预告/分红送转
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (UniqueConstraint("stock_symbol", "title", "announce_date", name="uix_announcement"),)


class FinancialReport(Base):
    """财务报表核心指标表"""
    __tablename__ = "financial_reports"

    id = Column(Integer, primary_key=True, index=True)
    stock_symbol = Column(String(20), nullable=False, index=True)
    report_date = Column(DateTime, nullable=False, index=True)       # 报告期
    report_type = Column(String(20), nullable=False)                 # 年报/中报/一季报/三季报
    # 资产负债表
    total_assets = Column(Float, nullable=True)
    total_liabilities = Column(Float, nullable=True)
    total_equity = Column(Float, nullable=True)
    current_assets = Column(Float, nullable=True)
    current_liabilities = Column(Float, nullable=True)
    # 利润表
    revenue = Column(Float, nullable=True)                           # 营业收入
    revenue_yoy = Column(Float, nullable=True)                       # 营收同比 %
    net_profit = Column(Float, nullable=True)                        # 归母净利润
    net_profit_yoy = Column(Float, nullable=True)                    # 净利润同比 %
    gross_margin = Column(Float, nullable=True)                      # 毛利率 %
    net_margin = Column(Float, nullable=True)                        # 净利率 %
    # 现金流
    operating_cf = Column(Float, nullable=True)                      # 经营活动现金流
    investing_cf = Column(Float, nullable=True)
    financing_cf = Column(Float, nullable=True)
    # 每股指标
    eps = Column(Float, nullable=True)                               # 基本每股收益
    bvps = Column(Float, nullable=True)                              # 每股净资产
    # 收益率
    roe = Column(Float, nullable=True)                               # 净资产收益率 %
    roa = Column(Float, nullable=True)                               # 总资产收益率 %
    # 估值指标（从行情数据补充）
    pe_ttm = Column(Float, nullable=True)
    pb = Column(Float, nullable=True)
    source = Column(String(50), default="akshare")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (UniqueConstraint("stock_symbol", "report_date", name="uix_financial"),)


class CrawlStatus(Base):
    """数据采集状态表"""
    __tablename__ = "crawl_status"

    id = Column(Integer, primary_key=True, index=True)
    stock_symbol = Column(String(20), nullable=False, index=True)
    data_type = Column(String(30), nullable=False, index=True)          # news/announcements/financials
    status = Column(String(20), nullable=False, default="success")     # success/error
    source = Column(String(100), nullable=True)
    fetched_count = Column(Integer, default=0)
    saved_count = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    finished_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)

    __table_args__ = (UniqueConstraint("stock_symbol", "data_type", name="uix_crawl_status_latest"),)


class StockNews(Base):
    """个股新闻表（含情感标记）"""
    __tablename__ = "stock_news"

    id = Column(Integer, primary_key=True, index=True)
    stock_symbol = Column(String(20), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    summary = Column(Text, nullable=True)
    source = Column(String(100), nullable=False)                     # 东方财富/新浪/财联社
    url = Column(String(500), nullable=True)
    publish_time = Column(DateTime, nullable=False, index=True)
    sentiment = Column(String(10), default="中性")                   # 正面/中性/负面
    sentiment_score = Column(Float, default=0.0)                     # -1.0 ~ 1.0
    impact_level = Column(String(10), default="低")                   # 高/中/低
    event_category = Column(String(50), nullable=True)               # 经营/政策/市场/舆论
    related_sector = Column(String(100), nullable=True)              # 相关板块
    keywords = Column(JSON, nullable=True)                           # 关键词
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (UniqueConstraint("stock_symbol", "title", "publish_time", name="uix_stock_news"),)


class ResearchObservation(Base):
    """每日研究观察快照表"""
    __tablename__ = "research_observations"

    id = Column(Integer, primary_key=True, index=True)
    snapshot_date = Column(DateTime, nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    strategy_id = Column(String(50), nullable=False, index=True)
    regime = Column(String(30), nullable=False, index=True)
    score = Column(Float, nullable=False)
    score_breakdown_json = Column(JSON, nullable=True)
    evidence_chain_json = Column(JSON, nullable=True)
    factor_snapshot_json = Column(JSON, nullable=True)
    debate_json = Column(JSON, nullable=True)
    veto_result_json = Column(JSON, nullable=True)
    close_price = Column(Float, nullable=True)
    summary_text = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    __table_args__ = (UniqueConstraint("snapshot_date", "symbol", "strategy_id", name="uix_research_observation"),)


class ObservationReview(Base):
    """研究观察复盘记录表"""
    __tablename__ = "observation_reviews"

    id = Column(Integer, primary_key=True, index=True)
    observation_id = Column(Integer, ForeignKey("research_observations.id", ondelete="CASCADE"), nullable=False, index=True)
    review_offset = Column(String(10), nullable=False, index=True)
    review_date = Column(DateTime, nullable=False, index=True)
    close_price = Column(Float, nullable=True)
    return_pct = Column(Float, nullable=True)
    max_drawdown_pct = Column(Float, nullable=True)
    falsification_triggered = Column(Boolean, default=False)
    risk_signal_valid = Column(Boolean, default=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    __table_args__ = (UniqueConstraint("observation_id", "review_offset", name="uix_observation_review"),)


class WeightSuggestionAudit(Base):
    """Admin weight suggestion audit trail."""
    __tablename__ = "weight_suggestion_audits"

    id = Column(Integer, primary_key=True, index=True)
    generated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    snapshot_from = Column(DateTime, nullable=True)
    snapshot_to = Column(DateTime, nullable=True)
    min_reviews = Column(Integer, nullable=False)
    status = Column(String(30), nullable=False)
    suggestions_json = Column(JSON, nullable=True)
    summary_json = Column(JSON, nullable=True)
    accepted = Column(Boolean, nullable=True)
    accepted_by = Column(Integer, nullable=True)
    accepted_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class StrategyWeightPatchProposal(Base):
    """Pending strategy weight patch generated from an accepted audit."""
    __tablename__ = "strategy_weight_patch_proposals"

    id = Column(Integer, primary_key=True, index=True)
    audit_id = Column(Integer, ForeignKey("weight_suggestion_audits.id", ondelete="CASCADE"), nullable=False, index=True)
    strategy_id = Column(String(50), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="pending", index=True)
    step = Column(Float, nullable=False)
    max_delta = Column(Float, nullable=False)
    before_json = Column(JSON, nullable=True)
    after_json = Column(JSON, nullable=True)
    delta_json = Column(JSON, nullable=True)
    items_json = Column(JSON, nullable=True)
    preview_json = Column(JSON, nullable=True)
    created_by = Column(Integer, nullable=True)
    decided_by = Column(Integer, nullable=True)
    decided_at = Column(DateTime, nullable=True)
    applied_by = Column(Integer, nullable=True)
    applied_at = Column(DateTime, nullable=True)
    applied_error = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)


class FinancialTrend(Base):
    """基本面趋势（季度更新，用于硬否决和乘法评分）"""
    __tablename__ = "financial_trends"

    id = Column(Integer, primary_key=True, index=True)
    stock_code = Column(String(20), nullable=False, index=True)
    report_date = Column(String(10), nullable=False)
    revenue = Column(Float, nullable=True)
    revenue_yoy = Column(Float, nullable=True)
    net_profit = Column(Float, nullable=True)
    profit_yoy = Column(Float, nullable=True)
    operating_cashflow = Column(Float, nullable=True)
    roe = Column(Float, nullable=True)
    revenue_decline_quarters = Column(Integer, default=0)
    profit_decline_quarters = Column(Integer, default=0)
    cashflow_negative_quarters = Column(Integer, default=0)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (UniqueConstraint("stock_code", "report_date", name="uix_financial_trend"),)


class PipelineRunLog(Base):
    """Pipeline 运行日志表"""
    __tablename__ = "pipeline_run_logs"

    id = Column(Integer, primary_key=True, index=True)
    run_date = Column(String(10), nullable=False, index=True)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=True)
    status = Column(String(20), nullable=False, default="running")
    total_collected = Column(Integer, default=0)
    total_screened = Column(Integer, default=0)
    total_scored = Column(Integer, default=0)
    final_pool_size = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    industries_collected = Column(Integer, default=0)
    after_screening = Column(Integer, default=0)
    after_hard_veto = Column(Integer, default=0)
    after_scoring = Column(Integer, default=0)
    vetoed_by_industry = Column(Integer, default=0)
    vetoed_by_acceleration = Column(Integer, default=0)
    vetoed_by_peer = Column(Integer, default=0)
    vetoed_by_fundamental = Column(Integer, default=0)
    vetoed_by_valuation = Column(Integer, default=0)
    vetoed_by_risk = Column(Integer, default=0)
    duration_seconds = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (UniqueConstraint("run_date", name="uix_pipeline_run_date"),)


class RejectionLog(Base):
    """Pipeline淘汰/近选明细"""
    __tablename__ = "rejection_logs"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    stock_name = Column(String(50), nullable=True)
    trade_date = Column(String(10), nullable=False, index=True)
    reject_stage = Column(String(30), nullable=False)
    reject_reason = Column(Text, nullable=True)
    reject_detail = Column(JSON, nullable=True)
    base_score = Column(Float, nullable=True)
    final_score = Column(Float, nullable=True)
    almost_qualified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class DailySnapshot(Base):
    """全市场每日行情快照（定时采集，用于异动筛选）"""
    __tablename__ = "daily_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    trade_date = Column(String(10), nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    name = Column(String(100), nullable=True)
    market = Column(String(10), nullable=False)
    open = Column(Float, nullable=True)
    high = Column(Float, nullable=True)
    low = Column(Float, nullable=True)
    close = Column(Float, nullable=True)
    prev_close = Column(Float, nullable=True)
    change_pct = Column(Float, nullable=True)
    volume = Column(Float, nullable=True)
    turnover = Column(Float, nullable=True)
    turnover_rate = Column(Float, nullable=True)
    total_mv = Column(Float, nullable=True)
    circ_mv = Column(Float, nullable=True)
    vol_ratio_5d = Column(Float, nullable=True)
    ma5 = Column(Float, nullable=True)
    ma20 = Column(Float, nullable=True)
    ma60 = Column(Float, nullable=True)
    source = Column(String(20), default="tencent")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (UniqueConstraint("trade_date", "symbol", name="uix_daily_snapshot"),)


class IndustryDailySnapshot(Base):
    """行业板块每日行情快照"""
    __tablename__ = "industry_daily_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    industry_code = Column(String(20), nullable=False, index=True)
    industry_name = Column(String(50), nullable=False)
    trade_date = Column(String(10), nullable=False, index=True)
    close = Column(Float, nullable=True)
    change_pct = Column(Float, nullable=True)
    ma5 = Column(Float, nullable=True)
    ma20 = Column(Float, nullable=True)
    ma60 = Column(Float, nullable=True)
    ret_5d = Column(Float, nullable=True)
    ret_20d = Column(Float, nullable=True)
    ret_60d = Column(Float, nullable=True)
    money_flow_1d = Column(Float, nullable=True)
    money_flow_5d = Column(Float, nullable=True)
    money_flow_20d = Column(Float, nullable=True)
    source = Column(String(20), default="akshare")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (UniqueConstraint("industry_code", "trade_date", name="uix_industry_daily_snapshot"),)


class IndustryHealthScore(Base):
    """行业健康评分（每日计算）"""
    __tablename__ = "industry_health_scores"

    id = Column(Integer, primary_key=True, index=True)
    industry_code = Column(String(20), nullable=False, index=True)
    industry_name = Column(String(50), nullable=False)
    trade_date = Column(String(10), nullable=False, index=True)
    health_score = Column(Integer, nullable=True)
    trend_score = Column(Integer, nullable=True)
    money_score = Column(Integer, nullable=True)
    momentum_score = Column(Integer, nullable=True)
    flags = Column(JSON, nullable=True)
    is_healthy = Column(Boolean, default=True)
    score_5d_ago = Column(Integer, nullable=True)
    score_change_5d = Column(Integer, nullable=True)
    is_accelerating_down = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (UniqueConstraint("industry_code", "trade_date", name="uix_industry_health_score"),)


class StrategyWeightVersion(Base):
    """Applied strategy weight config version for rollback."""
    __tablename__ = "strategy_weight_versions"

    id = Column(Integer, primary_key=True, index=True)
    strategy_id = Column(String(50), nullable=False, index=True)
    proposal_id = Column(Integer, ForeignKey("strategy_weight_patch_proposals.id", ondelete="SET NULL"), nullable=True, index=True)
    version = Column(Integer, nullable=False, index=True)
    before_json = Column(JSON, nullable=True)
    after_json = Column(JSON, nullable=True)
    applied_by = Column(Integer, nullable=True)
    applied_at = Column(DateTime, nullable=True)
    rolled_back_by = Column(Integer, nullable=True)
    rolled_back_at = Column(DateTime, nullable=True)
    rollback_error = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
