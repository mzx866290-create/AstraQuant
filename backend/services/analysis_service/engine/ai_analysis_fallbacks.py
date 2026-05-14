from __future__ import annotations

from backend.services.analysis_service.engine.data_quality import DataQualityBuilder, is_valid_number
from backend.services.analysis_service.engine.prompt_builder import fmt_billion, fmt_price


def _safe_number(value) -> float | None:
    try:
        result = float(value)
        return result if result == result else None  # NaN check
    except (TypeError, ValueError):
        return None


def _safe_change_pct(value) -> float | None:
    result = _safe_number(value)
    if result is None:
        return None
    return result if -30 <= result <= 30 else None


def build_fallback_analysis(symbol: str, stock_data: dict, error_message: str, audience: str = "normal") -> str:
    name = stock_data.get("name", symbol)
    financial = stock_data.get("financial") or {}
    sentiment = stock_data.get("news_sentiment") or {}
    industry_event = stock_data.get("industry_event_context") or {}
    risk_lights = build_risk_lights(stock_data)
    beginner_note = (
        "\n- 小白解释：PE/PB缺失时不能判断贵不贵；经营现金流为负时，要观察利润是否真正变成现金。"
        if audience == "beginner"
        else ""
    )
    lines = [
        "## AI模型失败，当前为本地规则摘要",
        "",
        f"> 模型调用失败：{error_message[:300]}。以下内容由本地结构化数据生成，不是大模型深度分析。",
        "",
        "## 摘要结论",
        f"- 股票：{symbol} {name}",
        f"- 行情：{fmt_price(stock_data.get('price'))}"
        + ("" if fmt_price(stock_data.get("price")) == "行情不可用" else f"；涨跌幅：{stock_data.get('change_pct', 'N/A')}%"),
        f"- 估值：PE(TTM) {financial.get('pe_ttm', 'N/A')}；PB {financial.get('pb', 'N/A')}",
        f"- 财报：营收 {fmt_billion(financial.get('revenue'))}，归母净利润 {fmt_billion(financial.get('net_profit'))}，经营现金流 {fmt_billion(financial.get('operating_cf'))}",
        beginner_note,
        "",
        "## 风险灯",
    ]
    for _key, item in risk_lights.items():
        lines.append(f"- {item['label']}：{item['level']}，{item['message']}")
    if sentiment and sentiment.get("total", 0) > 0:
        lines.extend(
            [
                "",
                "## 情绪校验",
                f"- 数量主导：{sentiment.get('count_dominant_sentiment', sentiment.get('dominant_sentiment', 'N/A'))}",
                f"- 加权主导：{sentiment.get('weighted_dominant_sentiment', sentiment.get('dominant_sentiment', 'N/A'))}",
                f"- 说明：{sentiment.get('validation_note', '')}",
            ]
        )
    if industry_event.get("themes"):
        lines.extend(["", "## 社会/政策/行业事件影响"])
        for theme in industry_event.get("themes", [])[:3]:
            evidence = theme.get("evidence") or []
            title = evidence[0].get("title", "") if evidence else ""
            lines.append(
                f"- {theme.get('theme')}：{theme.get('direction')}，置信度 {theme.get('confidence')}。"
                f"{theme.get('note', '')} 依据：{title}"
            )
        lines.append("- 以上仅为行业层面间接线索，不能等同于个股公告或公司业绩事实。")
    lines.append(build_source_citation(symbol, stock_data))
    return "\n".join([line for line in lines if line is not None])


def build_follow_up_fallback(question: str, error_message: str) -> str:
    return "\n".join(
        [
            "## 暂时无法完成追问",
            "",
            f"- 追问：{question[:200]}",
            f"- 模型错误：{error_message[:240]}",
            "",
            "你可以先回到原报告里看三件事：结论依据、最大风险、后续跟踪指标。若问题涉及买卖决策，请把它拆成：什么事实会支持继续观察，什么事实会推翻原逻辑，下一次财报或公告要验证什么。",
            "",
            "以上解读仅供学习和参考，不构成投资建议。",
        ]
    )


def build_batch_brief(symbol: str, stock_data: dict, audience: str) -> str:
    financial = stock_data.get("financial") or {}
    sentiment = stock_data.get("news_sentiment") or {}
    industry_event = stock_data.get("industry_event_context") or {}
    data_quality = stock_data.get("data_quality") or DataQualityBuilder.from_stock_data(stock_data)
    quote_warnings = set((data_quality.get("quote") or {}).get("warnings") or [])
    name = stock_data.get("name", symbol)
    if fmt_price(stock_data.get("price")) == "行情不可用":
        parts = [f"{name} 行情暂不可用，不能判断当前价格和短线走势。"]
    else:
        parts = [f"{name} 最新价 {fmt_price(stock_data.get('price'))}，涨跌幅 {stock_data.get('change_pct', 'N/A')}%。"]
    if "delisting_or_delisted_stock_name" in quote_warnings:
        parts.append("名称显示存在退市风险，不能按普通沪深A股做交易分析。")
    elif "quote_trade_fields_missing_or_zero" in quote_warnings:
        parts.append("行情成交字段异常，当前价格只能作为存疑参考。")
    if financial:
        parts.append(
            f"最近财报营收 {fmt_billion(financial.get('revenue'))}，归母净利润 {fmt_billion(financial.get('net_profit'))}，经营现金流 {fmt_billion(financial.get('operating_cf'))}。"
        )
    else:
        parts.append("财报数据缺失，基本面判断需要谨慎。")
    if sentiment and sentiment.get("total", 0) > 0:
        parts.append(
            f"近7天新闻数量主导为 {sentiment.get('count_dominant_sentiment', 'N/A')}，加权主导为 {sentiment.get('weighted_dominant_sentiment', 'N/A')}。"
        )
    if industry_event.get("themes"):
        themes = "、".join(t.get("theme", "") for t in industry_event.get("themes", [])[:2] if t.get("theme"))
        if themes:
            parts.append(f"需额外关注行业/社会事件：{themes}，仅作为间接影响线索。")
    if audience == "beginner":
        parts.append("小白先看三件事：价格是否有效、PE/PB是否齐全、利润有没有现金流支持。")
    return "".join(parts)


def build_batch_error_item(symbol: str, report_mode: str, audience: str, error: str) -> dict:
    return {
        "symbol": symbol,
        "name": symbol,
        "price": None,
        "change_pct": None,
        "summary": f"{symbol} 数据加载失败，暂不能生成摘要。错误：{error[:160]}",
        "risk_lights": {
            "data": {"label": "数据风险", "level": "red", "message": "数据加载失败"},
            "valuation": {"label": "估值风险", "level": "yellow", "message": "估值无法判断"},
            "financial": {"label": "财务风险", "level": "yellow", "message": "财务数据不可用"},
            "news": {"label": "消息风险", "level": "yellow", "message": "新闻数据不可用"},
            "technical": {"label": "技术面风险", "level": "yellow", "message": "K线数据不可用"},
        },
        "change_alerts": [{"type": "error", "level": "high", "message": error[:160]}],
        "data_quality": {
            "quote": {"source": "", "updated_at": None, "freshness": "error", "confidence": "low", "is_fallback": False, "warnings": ["batch_item_failed"]},
        },
        "readiness": {"ready": False, "quality": "error", "blocking": [], "missing_context": ["quote", "kline", "financial", "announcements", "news"]},
        "report_mode": report_mode,
        "audience": audience,
        "model_status": "error",
        "batch_cache_hit": False,
        "force_refresh": False,
    }


def build_risk_lights(stock_data: dict) -> dict:
    financial = stock_data.get("financial") or {}
    sentiment = stock_data.get("news_sentiment") or {}
    quote = stock_data.get("quote") or {}
    news = stock_data.get("news") or []
    industry_event = stock_data.get("industry_event_context") or {}
    data_quality = stock_data.get("data_quality") or DataQualityBuilder.from_stock_data(stock_data)
    quote_warnings = set((data_quality.get("quote") or {}).get("warnings") or [])

    def level(has_warning: bool, severe: bool = False) -> str:
        if severe:
            return "red"
        return "yellow" if has_warning else "green"

    valuation_missing = not (
        is_valid_number(financial.get("pe_ttm") or quote.get("pe_ttm"))
        and is_valid_number(financial.get("pb") or quote.get("pb"))
    )

    change_pct = _safe_change_pct(stock_data.get("change_pct"))
    volume = _safe_number(quote.get("volume"))
    is_limit_up = change_pct is not None and change_pct >= 9.8
    is_limit_down = change_pct is not None and change_pct <= -9.8
    is_suspended = volume is not None and volume == 0 and not is_limit_up and not is_limit_down

    return {
        "data": {
            "label": "数据风险",
            "level": level(any(v.get("warnings") for v in data_quality.values()), bool(quote_warnings & {"delisting_or_delisted_stock_name", "quote_trade_fields_missing_or_zero"})),
            "message": (
                "行情异常或存在退市风险"
                if quote_warnings & {"delisting_or_delisted_stock_name", "quote_trade_fields_missing_or_zero"}
                else ("存在缺失或兜底数据" if any(v.get("warnings") for v in data_quality.values()) else "核心数据可用")
            ),
        },
        "limit_up": {
            "label": "涨停风险",
            "level": "red" if is_limit_up else "green",
            "message": f"当日涨幅 {change_pct:+.2f}%，疑似涨停，次日追高风险极大" if is_limit_up else "未触及涨停",
            "type": "limit_up",
        },
        "limit_down": {
            "label": "跌停风险",
            "level": "red" if is_limit_down else "green",
            "message": f"当日跌幅 {change_pct:+.2f}%，疑似跌停，流动性枯竭风险" if is_limit_down else "未触及跌停",
            "type": "limit_down",
        },
        "suspended": {
            "label": "停牌风险",
            "level": "red" if is_suspended else "green",
            "message": "成交量为零，疑似停牌或临时停牌" if is_suspended else "交易正常",
            "type": "suspended",
        },
        "valuation": {
            "label": "估值风险",
            "level": level(valuation_missing),
            "message": "PE/PB不完整，估值无法判断" if valuation_missing else "PE/PB可用于参考",
        },
        "financial": {
            "label": "财务风险",
            "level": level(not financial, financial.get("operating_cf") is not None and financial.get("operating_cf") < 0),
            "message": "经营现金流为负，关注回款质量" if financial.get("operating_cf") is not None and financial.get("operating_cf") < 0 else ("财务数据缺失" if not financial else "财务数据可读"),
        },
        "news": {
            "label": "消息风险",
            "level": level(not news or sentiment.get("weighted_dominant_sentiment") in ("negative", "负面")),
            "message": sentiment.get("validation_note") or ("新闻数据缺失，消息面无法判断" if not news else "暂无明显消息风险"),
        },
        "industry_events": {
            "label": "行业事件风险",
            "level": level(not industry_event.get("available")),
            "message": (
                industry_event.get("note")
                if industry_event.get("available")
                else "社会/政策/行业新闻缺失，无法判断间接行业影响"
            ),
        },
        "technical": {
            "label": "技术面风险",
            "level": level(not stock_data.get("kline_data")),
            "message": "K线缺失，无法判断趋势" if not stock_data.get("kline_data") else "K线可用于趋势参考",
        },
    }


def build_change_alerts(stock_data: dict) -> list[dict]:
    alerts = []
    if abs(float(stock_data.get("change_pct") or 0)) >= 5:
        alerts.append({"type": "price", "level": "high", "message": f"日涨跌幅 {stock_data.get('change_pct')}%"})
    if stock_data.get("announcements"):
        latest = stock_data["announcements"][0]
        alerts.append({"type": "announcement", "level": "medium", "message": latest.get("title", "")})
    sentiment = stock_data.get("news_sentiment") or {}
    if sentiment.get("weighted_dominant_sentiment") in ("negative", "负面"):
        alerts.append({"type": "sentiment", "level": "medium", "message": sentiment.get("validation_note", "加权情绪偏负面")})
    industry_event = stock_data.get("industry_event_context") or {}
    for theme in (industry_event.get("themes") or [])[:1]:
        alerts.append({"type": "industry_event", "level": "low", "message": f"{theme.get('theme')}：{theme.get('direction')}（行业间接线索）"})
    financial = stock_data.get("financial") or {}
    if financial.get("report_date"):
        alerts.append({"type": "financial", "level": "low", "message": f"最新财报期 {financial.get('report_date')}"})
    return alerts[:5]


def build_source_citation(symbol: str, stock_data: dict) -> str:
    lines = ["", "## 数据来源"]
    if stock_data.get("quote"):
        lines.append(f"- 实时行情/估值：{stock_data.get('quote_source') or '行情源'}")
    if stock_data.get("kline_data"):
        lines.append(f"- K线与技术指标：{stock_data.get('kline_source') or '行情源'}")
    if stock_data.get("financial"):
        fin = stock_data["financial"]
        lines.append(f"- 财务数据：{fin.get('source', '财报库')}，报告期 {fin.get('report_date', 'N/A')}")
        if fin.get("valuation_source"):
            lines.append(f"- PE/PB估值：{fin.get('valuation_source')}")
    if stock_data.get("announcements"):
        lines.append(f"- 公司公告：{len(stock_data['announcements'])}条，来源 CNINFO/本地库")
    if stock_data.get("news"):
        lines.append(f"- 财经新闻：{len(stock_data['news'])}条，来源公开新闻库")
    industry_event = stock_data.get("industry_event_context") or {}
    if industry_event.get("themes"):
        lines.append(f"- 社会/政策/行业事件：{len(industry_event['themes'])}个主题，来源公开新闻库与规则映射")
    sentiment = stock_data.get("news_sentiment") or {}
    if sentiment.get("total", 0) > 0:
        lines.append(f"- 情绪分析：近7天 {sentiment.get('total')} 条新闻，区分数量主导与加权主导")
    lines.append("")
    lines.append("> 所有数据来自公开信息源或本地缓存。AI分析仅供参考，不构成投资建议。")
    return "\n".join(lines)
