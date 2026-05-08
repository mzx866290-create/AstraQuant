"""
Pydantic 鏁版嵁楠岃瘉 Schema - DTO 瀹氫箟
"""
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List
from datetime import datetime


# ============ Stock Schemas ============
class StockBase(BaseModel):
    symbol: str
    name: str
    market: str
    sector: Optional[str] = None


class StockCreate(StockBase):
    pass


class StockResponse(StockBase):
    id: int
    list_date: Optional[datetime] = None
    is_active: bool
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ============ User Schemas ============
class UserBase(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: str = Field(..., pattern=r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')


class UserCreate(UserBase):
    password: str = Field(..., min_length=8, max_length=100)


class UserLogin(BaseModel):
    username: str
    password: str


class UserResponse(UserBase):
    id: int
    nickname: Optional[str] = None
    avatar_url: Optional[str] = None
    role: str
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


# ============ Watchlist Schemas ============
class WatchlistItemBase(BaseModel):
    stock_id: int


class WatchlistItemResponse(WatchlistItemBase):
    id: int
    sort_order: int
    added_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WatchlistBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)


class WatchlistCreate(WatchlistBase):
    pass


class WatchlistResponse(WatchlistBase):
    id: int
    user_id: int
    sort_order: int
    created_at: datetime
    items: List[WatchlistItemResponse] = []

    model_config = ConfigDict(from_attributes=True)


# ============ K绾挎暟鎹?Schemas ============
class KLineDataPoint(BaseModel):
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    change_pct: Optional[float] = None


class KLineResponse(BaseModel):
    symbol: str
    period: str
    count: int
    source: str
    data: List[KLineDataPoint]
    indicators: Optional[dict] = None


class QuoteResponse(BaseModel):
    symbol: str
    name: str
    price: float
    change: float
    change_pct: float
    volume: int
    turnover: float
    bid: float
    ask: float
    bid_volume: int
    ask_volume: int
    timestamp: datetime
    source: str


# ============ 浠锋牸棰勮 Schemas ============
class PriceAlertCreate(BaseModel):
    stock_id: int
    alert_type: str  # price_above/price_below/change_pct
    threshold: float


class PriceAlertResponse(PriceAlertCreate):
    id: int
    user_id: int
    is_active: bool
    triggered_at: Optional[datetime] = None
    created_at: datetime
    stock_symbol: Optional[str] = None
    stock_name: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# ============ 鎼滅储缁撴灉 Schemas ============
class SearchResultItem(BaseModel):
    id: int
    symbol: str
    name: str
    market: str


class SearchResponse(BaseModel):
    query: str
    count: int
    results: List[SearchResultItem]


# ============ AI 妯″瀷 Schemas ============
class AIModelCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    provider: str = Field(..., pattern=r"^(openai|anthropic|deepseek|custom)$")
    model_id: str = Field(..., min_length=1, max_length=100)
    api_base_url: Optional[str] = None
    api_key: str = Field(..., min_length=1)
    description: Optional[str] = None
    config: Optional[dict] = None
    is_active: bool = True
    sort_order: int = 0
    allowed_roles: str = "free,premium,admin"


class AIModelUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    provider: Optional[str] = Field(None, pattern=r"^(openai|anthropic|deepseek|custom)$")
    model_id: Optional[str] = Field(None, min_length=1, max_length=100)
    api_base_url: Optional[str] = None
    api_key: Optional[str] = None
    description: Optional[str] = None
    config: Optional[dict] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None
    allowed_roles: Optional[str] = None


class AIModelResponse(BaseModel):
    id: int
    name: str
    provider: str
    model_id: str
    api_base_url: Optional[str] = None
    description: Optional[str] = None
    config: Optional[dict] = None
    is_active: bool
    sort_order: int
    allowed_roles: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AIModelPublicResponse(BaseModel):
    """鐢ㄦ埛绔彲瑙佺殑妯″瀷淇℃伅锛堜笉鍚晱鎰熷瓧娈碉級"""
    id: int
    name: str
    provider: str
    description: Optional[str] = None
    health_status: Optional[str] = None
    health_latency_ms: Optional[int] = None
    health_checked_at: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# ============ AI 鍒嗘瀽 Schemas ============
class AIAnalysisRequest(BaseModel):
    model_id: int
    symbol: str = Field(..., min_length=1, max_length=20)
    question: Optional[str] = None  # 鐢ㄦ埛鑷畾涔夋彁闂紝榛樿涓虹患鍚堝垎鏋?    framework: Optional[str] = None  # 鍒嗘瀽妗嗘灦: technical/fundamental/valuation/event
    include_news: bool = True  # 鏄惁鍖呭惈杩戞湡鏂伴椈
    report_template: str = "quick"  # quick/professional/teaching
    report_mode: str = "summary"  # summary/detailed
    audience: str = "normal"  # normal/beginner
    prompt_style: str = "default"  # default/plain/beginner/professional/risk_control
    force_refresh: bool = False  # bypass same-day AI cache


class AIBatchSummaryRequest(BaseModel):
    symbols: List[str] = Field(..., min_length=1, max_length=30)
    report_mode: str = "summary"
    audience: str = "normal"
    include_news: bool = True
    force_refresh: bool = False


class AIFollowUpRequest(BaseModel):
    model_id: int
    symbol: str = Field(..., min_length=1, max_length=20)
    question: str = Field(..., min_length=2, max_length=500)
    analysis: str = Field(..., min_length=20, max_length=16000)
    report_meta: Optional[dict] = None
    prompt_style: str = "default"
    audience: str = "normal"


class AIAnalysisResponse(BaseModel):
    symbol: str
    model_name: str
    analysis: str  # Markdown 鏍煎紡鐨勫垎鏋愭姤鍛?    tokens_used: int
    response_time_ms: int
    created_at: datetime
    requested_model: Optional[str] = None
    actual_model: Optional[str] = None
    fallback_reason: Optional[str] = None
    data_quality: Optional[dict] = None
    readiness: Optional[dict] = None
    risk_lights: Optional[dict] = None
    trust_boundary: Optional[dict] = None
    report_meta: Optional[dict] = None
    cache_hit: bool = False


class AIFollowUpResponse(BaseModel):
    symbol: str
    model_name: str
    answer: str
    tokens_used: int
    response_time_ms: int
    created_at: datetime
    requested_model: Optional[str] = None
    actual_model: Optional[str] = None
    fallback_reason: Optional[str] = None
    report_meta: Optional[dict] = None


# ============ AI 璋冪敤鏃ュ織 Schemas ============
class AIUsageLogResponse(BaseModel):
    id: int
    user_id: int
    username: Optional[str] = None
    model_id: int
    model_name: Optional[str] = None
    stock_symbol: Optional[str] = None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost: float
    status: str
    error_message: Optional[str] = None
    response_time_ms: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserActivityLogResponse(BaseModel):
    id: int
    user_id: Optional[int] = None
    username: Optional[str] = None
    action: str
    target: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ============ 鐢ㄦ埛閰嶉 Schemas ============
class UserQuotaResponse(BaseModel):
    user_id: int
    daily_limit: int
    monthly_limit: int
    daily_used: int
    monthly_used: int
    daily_remaining: int = 0
    monthly_remaining: int = 0

    model_config = ConfigDict(from_attributes=True)


class UserQuotaUpdate(BaseModel):
    daily_limit: Optional[int] = Field(None, ge=0, le=10000)
    monthly_limit: Optional[int] = Field(None, ge=0, le=100000)


# ============ 绠＄悊缁熻 Schemas ============
class AdminStatsResponse(BaseModel):
    total_users: int
    active_users_today: int
    total_models: int
    active_models: int
    total_api_calls_today: int
    total_api_calls_month: int
    total_tokens_today: int
    total_cost_month: float
    calls_by_model: List[dict]       # [{model_name, count, tokens}]
    calls_by_day: List[dict]         # [{date, count}]
    top_users: List[dict]            # [{username, count}]


class AdminUserResponse(BaseModel):
    """Admin user list."""
    id: int
    username: str
    email: str
    nickname: Optional[str] = None
    role: str
    is_active: bool
    created_at: datetime
    daily_limit: int = 10
    monthly_limit: int = 100
    daily_used: int = 0
    monthly_used: int = 0

    model_config = ConfigDict(from_attributes=True)


class AdminUserUpdate(BaseModel):
    role: Optional[str] = Field(None, pattern=r"^(free|premium|admin)$")
    is_active: Optional[bool] = None
    daily_limit: Optional[int] = Field(None, ge=0, le=10000)
    monthly_limit: Optional[int] = Field(None, ge=0, le=100000)


# ============ 鍏憡 Schemas ============
class AnnouncementResponse(BaseModel):
    id: int
    stock_symbol: str
    title: str
    summary: Optional[str] = None
    content_url: Optional[str] = None
    announce_date: datetime
    source: str
    category: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# ============ 璐㈡姤 Schemas ============
class FinancialReportResponse(BaseModel):
    id: int
    stock_symbol: str
    report_date: datetime
    report_type: str
    revenue: Optional[float] = None
    revenue_yoy: Optional[float] = None
    net_profit: Optional[float] = None
    net_profit_yoy: Optional[float] = None
    gross_margin: Optional[float] = None
    net_margin: Optional[float] = None
    eps: Optional[float] = None
    bvps: Optional[float] = None
    roe: Optional[float] = None
    roa: Optional[float] = None
    total_assets: Optional[float] = None
    total_liabilities: Optional[float] = None
    total_equity: Optional[float] = None
    operating_cf: Optional[float] = None
    investing_cf: Optional[float] = None
    financing_cf: Optional[float] = None
    pe_ttm: Optional[float] = None
    pb: Optional[float] = None
    source: str

    model_config = ConfigDict(from_attributes=True)


class FinancialSummaryResponse(BaseModel):
    symbol: str
    reports: List[FinancialReportResponse]
    dupont: Optional[dict] = None
    f_score: Optional[dict] = None
    latest_pe: Optional[float] = None
    latest_pb: Optional[float] = None


# ============ 鏂伴椈 Schemas ============
class StockNewsResponse(BaseModel):
    id: int
    stock_symbol: str
    title: str
    summary: Optional[str] = None
    source: str
    url: Optional[str] = None
    publish_time: datetime
    sentiment: str
    sentiment_score: float
    impact_level: str
    event_category: Optional[str] = None
    related_sector: Optional[str] = None
    keywords: Optional[list] = None

    model_config = ConfigDict(from_attributes=True)


class NewsImpactResponse(BaseModel):
    symbol: str
    recent_news: List[StockNewsResponse]
    sentiment_summary: dict  # {positive: N, neutral: N, negative: N, avg_score: X}
    top_impact_events: List[StockNewsResponse]
    sector_news: List[StockNewsResponse]  # 鐩稿叧琛屼笟鏂伴椈


# ============ 璐㈠姟鍒嗘瀽 Schemas ============
class DuPontResponse(BaseModel):
    roe: float
    net_margin: float
    asset_turnover: float
    equity_multiplier: float
    interpretation: str


class FScoreResponse(BaseModel):
    score: int  # 0-9
    details: List[dict]  # [{criterion, passed, reason}]
    rating: str  # 浼樼/鑹ソ/涓€鑸?杈冨樊


class ValuationResponse(BaseModel):
    symbol: str
    current_pe: Optional[float] = None
    current_pb: Optional[float] = None
    pe_percentile: Optional[float] = None  # 褰撳墠PE鍦ㄥ巻鍙蹭腑鐨勫垎浣?
    pb_percentile: Optional[float] = None
    pe_band: dict  # {min, p25, median, p75, max, current}
    pb_band: dict
    dcf_estimate: Optional[dict] = None
