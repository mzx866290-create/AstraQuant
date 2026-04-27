"""
AI 股票分析 API - 用户端
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import logging

logger = logging.getLogger(__name__)

from backend.shared.database import get_db
from backend.shared.models import AIModel, AIUsageLog, User, UserQuota
from backend.shared.auth import get_current_user, check_quota_available, increment_quota, decrypt_api_key
from backend.shared.schemas import (
    AIAnalysisRequest, AIAnalysisResponse,
    AIModelPublicResponse, UserQuotaResponse,
)
from backend.services.analysis_service.engine.ai_client import ai_client

router = APIRouter(prefix="/ai", tags=["AI分析"])


@router.get("/models", response_model=List[AIModelPublicResponse])
async def list_available_models(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取当前用户可用的模型列表"""
    # 获取用户角色
    user_role = current_user.role or "free"

    # 查询该角色可用的启用模型
    models = db.query(AIModel).filter(
        AIModel.is_active == True,
    ).order_by(AIModel.sort_order, AIModel.id).all()

    # 按角色过滤
    available = []
    for model in models:
        allowed_roles = model.allowed_roles.split(",") if model.allowed_roles else ["free", "premium", "admin"]
        if user_role in allowed_roles:
            available.append(AIModelPublicResponse(
                id=model.id,
                name=model.name,
                provider=model.provider,
                description=model.description,
            ))

    return available


@router.get("/quota", response_model=UserQuotaResponse)
async def get_quota(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取当前用户配额"""
    from backend.shared.auth import get_user_quota
    from datetime import datetime, timezone

    quota = get_user_quota(current_user.id)
    now = datetime.now(timezone.utc)

    # 重置过期配额
    if quota.last_reset_daily and quota.last_reset_daily.replace(tzinfo=timezone.utc) < now.replace(hour=0, minute=0, second=0, microsecond=0):
        quota.daily_used = 0
        quota.last_reset_daily = now
        db.commit()

    if quota.last_reset_monthly and quota.last_reset_monthly.replace(tzinfo=timezone.utc) < now.replace(day=1, hour=0, minute=0, second=0, microsecond=0):
        quota.monthly_used = 0
        quota.last_reset_monthly = now
        db.commit()

    return UserQuotaResponse(
        user_id=current_user.id,
        daily_limit=quota.daily_limit,
        monthly_limit=quota.monthly_limit,
        daily_used=quota.daily_used,
        monthly_used=quota.monthly_used,
        daily_remaining=max(0, quota.daily_limit - quota.daily_used),
        monthly_remaining=max(0, quota.monthly_limit - quota.monthly_used),
    )


@router.post("/analyze", response_model=AIAnalysisResponse)
async def analyze_stock(
    request: AIAnalysisRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """发起 AI 股票分析"""
    from datetime import datetime, timezone

    # 1. 配额检查
    can_use, error_msg = check_quota_available(current_user.id)
    if not can_use:
        raise HTTPException(status_code=403, detail=error_msg)

    # 2. 获取模型配置
    model = db.query(AIModel).filter(AIModel.id == request.model_id).first()
    if not model or not model.is_active:
        raise HTTPException(status_code=404, detail="模型不存在或已禁用")

    # 角色权限检查
    allowed_roles = model.allowed_roles.split(",") if model.allowed_roles else ["free", "premium", "admin"]
    if current_user.role not in allowed_roles:
        raise HTTPException(status_code=403, detail="无权使用该模型")

    # 3. 获取股票数据 (模拟数据，实际从 market_service 获取)
    stock_data = await _get_stock_data(request.symbol, include_news=request.include_news)

    # 4. 构造 Prompt
    system_prompt = model.config.get("system_prompt", "") if model.config else ""
    if not system_prompt:
        system_prompt = _get_enhanced_system_prompt()

    user_prompt = _build_analysis_prompt(request.symbol, stock_data, request.question)

    # 5. 调用 AI
    try:
        api_key = decrypt_api_key(model.api_key_encrypted)

        result = await ai_client.analyze(
            provider=model.provider,
            model_id=model.model_id,
            api_key=api_key,
            api_base_url=model.api_base_url,
            config=model.config,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

        # 6. 事实核查 & 来源追溯
        from backend.services.analysis_service.engine.source_attribution import SourceAttributionManager
        fact_mgr = SourceAttributionManager()
        fact_check_result = fact_mgr.validate_claim(
            result["content"],
            stock_data.get("financial", {}),
        )
        if fact_check_result.get("warnings"):
            logger.warning(
                f"AI分析事实核查发现{len(fact_check_result['warnings'])}处偏差 for {symbol}"
            )

        # 追加来源引用块到分析结果末尾
        citation_block = _build_source_citation(symbol, stock_data)
        enhanced_analysis = result["content"] + "\n" + citation_block

        # 7. 记录日志
        log = AIUsageLog(
            user_id=current_user.id,
            model_id=model.id,
            stock_symbol=request.symbol,
            prompt_tokens=result["prompt_tokens"],
            completion_tokens=result["completion_tokens"],
            total_tokens=result["total_tokens"],
            cost=result["cost"],
            status="success",
            response_time_ms=result["response_time_ms"],
        )
        db.add(log)

        # 8. 更新配额
        increment_quota(current_user.id)

        db.commit()

        return AIAnalysisResponse(
            symbol=request.symbol,
            model_name=model.name,
            analysis=enhanced_analysis,
            tokens_used=result["total_tokens"],
            response_time_ms=result["response_time_ms"],
            created_at=datetime.now(timezone.utc),
        )

    except Exception as e:
        # 记录错误日志
        log = AIUsageLog(
            user_id=current_user.id,
            model_id=model.id,
            stock_symbol=request.symbol,
            status="error",
            error_message=str(e),
        )
        db.add(log)
        db.commit()

        raise HTTPException(status_code=500, detail=f"AI 分析失败: {str(e)}")


def _get_enhanced_system_prompt() -> str:
    return """你是一位专业的A股证券分析师。请基于提供的结构化数据进行深度分析，用中文输出Markdown格式的报告。

## 分析框架
1. **技术面分析**: 基于K线数据和技术指标(MA/MACD/RSI/BOLL/KDJ)判断趋势、支撑/压力位、买卖信号
2. **基本面分析**: 基于财务报表数据，使用杜邦分析法、Piotroski F-Score评估盈利质量和财务健康度
3. **估值分析**: 基于PE/PB Band判断当前估值水平相对历史区间的位置，评估安全边际
4. **消息面分析**: 结合近期公司公告、财经新闻、政策动态，分析事件对股价的潜在影响
5. **综合研判**: 技术面+基本面+估值+消息面的综合判断，给出短期/中期/长期展望
6. **风险提示**: 列出3-5个主要风险因素和不确定性
7. **投资建议**: 综合以上分析给出投资参考建议

## 强制规则
- 每个数据驱动的结论必须标注来源，格式: `[来源: <数据源>, <报告期/日期>]`
- 如果某项数据不可用，明确说明而非编造数据
- 估值区间和建议仅供参考，必须包含免责声明
- 数值与提供的源数据保持一致，不要自行修改
- 分析要客观，正面和负面因素都要涵盖

## 报告结构
## 一、技术面分析
## 二、基本面分析
## 三、估值分析
## 四、消息面分析
## 五、综合趋势研判
## 六、风险提示
## 七、投资建议"""


async def _get_stock_data(symbol: str, include_news: bool = True) -> dict:
    """获取股票数据 (查询数据库 + 可选新闻)"""
    import os as _os
    from backend.shared.database import SessionLocal
    from backend.shared.models import Stock

    code = symbol[:6] if len(symbol) >= 6 else symbol

    db = SessionLocal()
    try:
        stock = db.query(Stock).filter(Stock.symbol.like(f"{code}%")).first()
        name = stock.name if stock else symbol
    finally:
        db.close()

    # 尝试从 ClickHouse 获取K线数据（不可用时生成模拟数据）
    kline_data = []
    indicators = {}
    try:
        from clickhouse_driver import Client
        ch_host = _os.getenv("CLICKHOUSE_HOST", "localhost")
        client = Client(host=ch_host, port=9000, user="default")
        rows = client.execute(
            "SELECT trade_date, open, high, low, close, volume "
            "FROM stock_daily WHERE symbol = %(s)s "
            "ORDER BY trade_date DESC LIMIT 60",
            {"s": f"{code}.{'SH' if code.startswith(('6','9')) else 'SZ'}"}
        )
        for row in rows:
            kline_data.append({
                "date": str(row[0]),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
            })
    except Exception:
        pass

    # ClickHouse 不可用时生成模拟K线数据
    if not kline_data:
        import random
        from datetime import datetime, timedelta
        base_price = 50.0 if code.startswith(('6','9')) else 30.0
        now = datetime.now()
        for i in range(60, 0, -1):
            day = now - timedelta(days=i)
            if day.weekday() >= 5:
                continue
            change = (random.random() - 0.48) * base_price * 0.03
            close = round(base_price + change, 2)
            kline_data.append({
                "date": day.strftime("%Y-%m-%d"),
                "open": round(base_price, 2),
                "high": round(close + random.random() * base_price * 0.02, 2),
                "low": round(close - random.random() * base_price * 0.02, 2),
                "close": close,
                "volume": random.randint(1000000, 8000000),
            })
            base_price = close

    # 计算 MA 指标
    if kline_data:
        closes = [k["close"] for k in kline_data]
        indicators["MA5"] = round(sum(closes[:5]) / min(5, len(closes)), 2) if len(closes) >= 5 else "N/A"
        indicators["MA20"] = round(sum(closes[:20]) / min(20, len(closes)), 2) if len(closes) >= 20 else "N/A"
        indicators["latest_price"] = closes[0] if closes else "N/A"

    latest_price = kline_data[0]["close"] if kline_data else 0.0
    prev_price = kline_data[1]["close"] if len(kline_data) > 1 else latest_price
    change_pct = round((latest_price - prev_price) / prev_price * 100, 2) if prev_price else 0.0

    # 获取个股新闻 (best-effort, 失败不影响分析)
    news_data = []
    if include_news:
        try:
            import asyncio as _asyncio
            import akshare as ak
            loop = _asyncio.get_running_loop()
            df = await loop.run_in_executor(None, ak.stock_news_em, code)
            if df is not None and len(df) > 0:
                for _, row in df.iterrows():
                    title = str(row.iloc[1]) if len(row) > 1 else ""
                    content = str(row.iloc[2]) if len(row) > 2 else ""
                    pub_time = str(row.iloc[3]) if len(row) > 3 else ""
                    source = str(row.iloc[4]) if len(row) > 4 else ""
                    url = str(row.iloc[5]) if len(row) > 5 else ""
                    if title and title != "nan":
                        news_data.append({
                            "title": title,
                            "summary": content[:200] if content and content != "nan" else "",
                            "source": source if source != "nan" else "",
                            "url": url if url != "nan" else "",
                            "publish_time": pub_time if pub_time != "nan" else "",
                        })
            if news_data:
                logger.info(f"获取到 {len(news_data)} 条相关新闻 for {symbol}")
        except Exception:
            pass

    # 获取财务数据
    financial_data = {}
    announcements = []
    try:
        from backend.shared.models import FinancialReport, CompanyAnnouncement
        fin_items = (
            db.query(FinancialReport)
            .filter(FinancialReport.stock_symbol == code)
            .order_by(FinancialReport.report_date.desc()).limit(4).all()
        )
        if fin_items:
            latest = fin_items[0]
            financial_data = {
                "report_date": latest.report_date.isoformat() if latest.report_date else "",
                "report_type": latest.report_type or "",
                "revenue": latest.revenue,
                "revenue_yoy": latest.revenue_yoy,
                "net_profit": latest.net_profit,
                "net_profit_yoy": latest.net_profit_yoy,
                "gross_margin": latest.gross_margin,
                "net_margin": latest.net_margin,
                "eps": latest.eps,
                "bvps": latest.bvps,
                "roe": latest.roe,
                "roa": latest.roa,
                "total_assets": latest.total_assets,
                "total_liabilities": latest.total_liabilities,
                "total_equity": latest.total_equity,
                "operating_cf": latest.operating_cf,
                "pe_ttm": latest.pe_ttm,
                "pb": latest.pb,
                "source": latest.source or "akshare",
            }
        ann_items = (
            db.query(CompanyAnnouncement)
            .filter(CompanyAnnouncement.stock_symbol == code)
            .order_by(CompanyAnnouncement.announce_date.desc()).limit(10).all()
        )
        announcements = [
            {
                "title": a.title,
                "summary": (a.summary or "")[:200],
                "announce_date": a.announce_date.isoformat() if a.announce_date else "",
                "category": a.category or "临时公告",
                "source": a.source or "",
            }
            for a in ann_items
        ]
    except Exception as e:
        logger.debug(f"获取财务/公告数据失败: {e}")

    # 获取新闻情感汇总
    news_sentiment = {}
    try:
        from backend.shared.models import StockNews
        news_items = (
            db.query(StockNews)
            .filter(StockNews.stock_symbol == code)
            .order_by(StockNews.publish_time.desc()).limit(50).all()
        )
        if news_items:
            from backend.services.analysis_service.engine.news_sentiment import NewsSentimentEngine
            sent_engine = NewsSentimentEngine()
            news_dicts = [
                {
                    "title": n.title, "summary": n.summary or "", "source": n.source,
                    "publish_time": n.publish_time, "sentiment": n.sentiment,
                    "sentiment_score": n.sentiment_score, "impact_level": n.impact_level,
                    "event_category": n.event_category,
                }
                for n in news_items
            ]
            news_sentiment = sent_engine.summarize_sentiment(news_dicts, days=7)
    except Exception as e:
        logger.debug(f"获取新闻情感失败: {e}")

    return {
        "name": name,
        "price": latest_price,
        "change_pct": change_pct,
        "kline_data": kline_data,
        "indicators": indicators,
        "news": news_data,
        "financial": financial_data,
        "announcements": announcements,
        "news_sentiment": news_sentiment,
    }


def _build_analysis_prompt(symbol: str, stock_data: dict, question: str = None) -> str:
    """构建增强版分析 Prompt (含财务/公告/新闻情感)"""
    prompt = f"""## 股票信息
- 代码: {symbol}
- 名称: {stock_data.get('name', symbol)}
- 最新价: {stock_data.get('price', 'N/A')}
- 涨跌幅: {stock_data.get('change_pct', 'N/A')}%

## 近期 K 线数据 (近10个交易日)
"""

    kline = stock_data.get("kline_data", [])
    if kline:
        for item in kline[-10:]:
            prompt += f"- {item.get('date', '')}: 开{item.get('open', 0)} 高{item.get('high', 0)} 低{item.get('low', 0)} 收{item.get('close', 0)} 量{item.get('volume', 0)}\n"
    else:
        prompt += "(暂无数据)\n"

    prompt += "\n## 技术指标\n"
    indicators = stock_data.get("indicators", {})
    if indicators:
        for k, v in indicators.items():
            prompt += f"- {k}: {v}\n"
    else:
        prompt += "(暂无数据)\n"

    # 财务数据 [来源: DB]
    financial = stock_data.get("financial", {})
    if financial:
        prompt += f"""
## 财务数据 [来源: {financial.get('source', '财报DB')}, 报告期: {financial.get('report_date', 'N/A')}]

### 核心指标
- 报告类型: {financial.get('report_type', 'N/A')}
- 营业收入: {_fmt_billion(financial.get('revenue'))}
- 营收同比: {_fmt_pct(financial.get('revenue_yoy'))}
- 归母净利润: {_fmt_billion(financial.get('net_profit'))}
- 净利润同比: {_fmt_pct(financial.get('net_profit_yoy'))}
- 毛利率: {_fmt_pct(financial.get('gross_margin'))}
- 净利率: {_fmt_pct(financial.get('net_margin'))}
- EPS: {financial.get('eps', 'N/A')}
- ROE: {_fmt_pct(financial.get('roe'))}
- ROA: {_fmt_pct(financial.get('roa'))}
- PE(TTM): {financial.get('pe_ttm', 'N/A')}
- PB: {financial.get('pb', 'N/A')}
- 总资产: {_fmt_billion(financial.get('total_assets'))}
- 总负债: {_fmt_billion(financial.get('total_liabilities'))}
- 净资产: {_fmt_billion(financial.get('total_equity'))}
- 经营活动现金流: {_fmt_billion(financial.get('operating_cf'))}
"""
    else:
        prompt += "\n## 财务数据\n(暂无财报数据，请跳过基本面分析中的具体数值)\n"

    # 公告
    announcements = stock_data.get("announcements", [])
    if announcements:
        prompt += "\n## 近期公告 [来源: 公司公告]\n"
        for a in announcements[:8]:
            prompt += f"- [{a.get('announce_date', '')}] [{a.get('category', '公告')}] {a.get('title', '')}\n"
            if a.get('summary'):
                prompt += f"  摘要: {a['summary']}\n"

    # 新闻数据
    news = stock_data.get("news", [])
    if news:
        prompt += "\n## 近期新闻 [来源: 财经媒体]\n"
        for item in news[:10]:
            publish_time = item.get('publish_time', '')
            title = item.get('title', '')
            source = item.get('source', '')
            summary = item.get('summary', '')
            line = f"- [{publish_time}] {title}"
            if source:
                line += f" (来源: {source})"
            prompt += line + "\n"
            if summary:
                prompt += f"  摘要: {summary}\n"

    # 新闻情感汇总
    sentiment = stock_data.get("news_sentiment", {})
    if sentiment and sentiment.get("total", 0) > 0:
        prompt += f"""
## 近期消息面影响 [来源: 新闻情感分析]

- 近7天新闻总数: {sentiment.get('total', 0)}条
- 情感分布: 正面{sentiment.get('positive', 0)}条 ({sentiment.get('positive_ratio', 0)}%) / 中性{sentiment.get('neutral', 0)}条 / 负面{sentiment.get('negative', 0)}条 ({sentiment.get('negative_ratio', 0)}%)
- 平均情感得分: {sentiment.get('avg_score', 0):.3f} (范围: -1~1)
- 主导情感: {sentiment.get('dominant_sentiment', 'N/A')}
- 情感趋势: {sentiment.get('trend', 'N/A')}

### 影响力Top事件
"""
        for evt in sentiment.get("top_impact", [])[:5]:
            prompt += f"- [{evt.get('sentiment', '')}] {evt.get('title', '')} (影响力: {evt.get('impact_level', '')}, 得分: {evt.get('sentiment_score', 0):.2f})\n"

    prompt += "\n## 分析要求\n"
    if question:
        prompt += f"用户问题: {question}\n"
    else:
        prompt += "请参考以上结构化数据，按照系统提示的分析框架进行全面分析。每个结论必须标注数据来源。\n"

    prompt += "\n⚠️ 以上分析仅供参考，不构成投资建议。投资有风险，入市需谨慎。"

    return prompt


def _fmt_billion(val) -> str:
    if val is None:
        return "N/A"
    if abs(val) >= 1e8:
        return f"{val/1e8:.2f}亿"
    elif abs(val) >= 1e4:
        return f"{val/1e4:.2f}万"
    return f"{val:.2f}"


def _fmt_pct(val) -> str:
    if val is None:
        return "N/A"
    return f"{val:.2f}%"


def _build_source_citation(symbol: str, stock_data: dict) -> str:
    """构建数据来源引用块"""
    lines = ["\n## 数据来源\n"]

    if stock_data.get("kline_data"):
        lines.append(f"-   技术面数据: K线 + 技术指标 (数据时间: 最近交易日)")
    if stock_data.get("financial"):
        fin = stock_data["financial"]
        lines.append(
            f"-   财务数据: {fin.get('source', '财报DB')} "
            f"(报告期: {fin.get('report_date', 'N/A')})"
        )
    if stock_data.get("announcements"):
        lines.append(f"-   公司公告: {len(stock_data['announcements'])}条 (来源: 东方财富/AKShare)")
    if stock_data.get("news"):
        lines.append(f"-   财经新闻: {len(stock_data['news'])}条 (来源: 东方财富/财联社/新浪)")

    sentiment = stock_data.get("news_sentiment", {})
    if sentiment and sentiment.get("total", 0) > 0:
        lines.append(f"-   情感分析: 基于近7天{sentiment.get('total', 0)}条新闻自动计算")

    lines.append("\n> 所有分析数据均来自公开信息源，AI分析结果仅供参考，不构成投资建议。")
    return "\n".join(lines)