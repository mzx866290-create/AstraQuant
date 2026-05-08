from __future__ import annotations

from datetime import datetime
from typing import Any


class IndustryEventImpactEngine:
    """Map broad social, policy, and industry news to likely A-share sector impact."""

    RULES = [
        {
            "theme": "消费刺激与假期消费",
            "keywords": ["消费", "促消费", "社零", "以旧换新", "假期", "旅游", "餐饮", "免税"],
            "positive_sectors": ["食品饮料", "商贸零售", "社会服务", "旅游", "酒店", "家电", "汽车"],
            "negative_sectors": [],
            "direction": "positive",
            "note": "消费政策和客流修复通常先影响消费链条，个股兑现仍要看收入和利润。",
        },
        {
            "theme": "房地产政策",
            "keywords": ["房地产", "楼市", "房贷", "首付", "限购", "保交楼", "城中村", "地产"],
            "positive_sectors": ["房地产", "建筑材料", "建筑装饰", "家居用品", "银行", "非银金融"],
            "negative_sectors": [],
            "direction": "positive",
            "note": "地产政策会影响地产链和金融链，但传导强弱取决于成交和信用修复。",
        },
        {
            "theme": "AI算力与数字经济",
            "keywords": ["AI", "人工智能", "大模型", "算力", "数据中心", "服务器", "光模块", "半导体", "机器人"],
            "positive_sectors": ["计算机", "通信", "电子", "传媒", "机械设备", "安防", "智能物联", "软件"],
            "negative_sectors": [],
            "direction": "positive",
            "note": "AI主题偏产业催化，需区分真实订单、业绩贡献和题材交易。",
        },
        {
            "theme": "医药政策与公共卫生",
            "keywords": ["医保", "集采", "创新药", "医疗", "流感", "公共卫生", "药品", "器械"],
            "positive_sectors": ["医药生物", "医疗器械", "创新药"],
            "negative_sectors": ["仿制药", "高值耗材"],
            "direction": "mixed",
            "note": "医药新闻经常分化，创新和需求端偏正面，集采降价对部分品类偏压力。",
        },
        {
            "theme": "极端天气与能源保供",
            "keywords": ["高温", "寒潮", "暴雨", "洪涝", "干旱", "台风", "电力保供", "迎峰度夏"],
            "positive_sectors": ["公用事业", "电力", "煤炭", "水利", "农业", "保险"],
            "negative_sectors": ["旅游", "交通运输", "农业"],
            "direction": "mixed",
            "note": "天气事件影响具有区域性和时效性，可能同时带来保供需求和受灾损失。",
        },
        {
            "theme": "出口、关税与汇率",
            "keywords": ["出口", "关税", "贸易摩擦", "汇率", "人民币", "美元", "外需", "海外订单"],
            "positive_sectors": ["家用电器", "纺织服饰", "汽车", "电子", "机械设备"],
            "negative_sectors": ["航空", "进口依赖", "美元债"],
            "direction": "mixed",
            "note": "外需和汇率影响要结合出口占比、原材料进口和海外收入结构判断。",
        },
        {
            "theme": "油价与地缘风险",
            "keywords": ["油价", "原油", "OPEC", "地缘", "冲突", "航运", "天然气"],
            "positive_sectors": ["石油石化", "煤炭", "航运", "军工"],
            "negative_sectors": ["航空", "化工", "交通运输"],
            "direction": "mixed",
            "note": "油价上行利好上游资源，但会抬升航空、化工和运输成本。",
        },
        {
            "theme": "资本市场与流动性政策",
            "keywords": ["降准", "降息", "流动性", "活跃资本市场", "印花税", "融资融券", "回购增持"],
            "positive_sectors": ["非银金融", "证券", "银行", "沪深300", "A股"],
            "negative_sectors": [],
            "direction": "positive",
            "note": "流动性政策先影响风险偏好，再通过成交、估值和资金面传导到行业。",
        },
        {
            "theme": "安全生产与环保监管",
            "keywords": ["安全生产", "环保", "限产", "停产", "检查", "监管", "排放"],
            "positive_sectors": ["环保", "龙头企业"],
            "negative_sectors": ["化工", "钢铁", "有色金属", "建材"],
            "direction": "mixed",
            "note": "监管趋严可能压制高耗能供给，也可能提升合规龙头集中度。",
        },
    ]

    MARKET_WIDE_KEYWORDS = [
        "国务院",
        "发改委",
        "央行",
        "证监会",
        "财政部",
        "工信部",
        "政策",
        "行业",
        "全国",
        "社会",
        "消费",
        "出口",
        "地产",
        "AI",
        "人工智能",
        "大模型",
        "算力",
    ]

    @classmethod
    def analyze(cls, stock_name: str, sector: str | None, market_news: list[dict[str, Any]], limit: int = 5) -> dict:
        stock_name = stock_name or ""
        sector = sector or ""
        if not market_news:
            return {
                "available": False,
                "sector": sector,
                "themes": [],
                "warnings": ["industry_event_news_missing"],
                "note": "未取得市场/社会/行业新闻，无法判断间接行业影响。",
            }

        themes: list[dict[str, Any]] = []
        for rule in cls.RULES:
            evidence = []
            for item in market_news:
                text = cls._text(item)
                if not cls._news_matches_rule(text, rule):
                    continue
                if not cls._is_relevant_to_stock(rule, item, sector, stock_name, text):
                    continue
                evidence.append(cls._evidence(item))
                if len(evidence) >= 3:
                    break
            if evidence:
                themes.append(
                    {
                        "theme": rule["theme"],
                        "direction": cls._direction_for_sector(rule, sector, stock_name),
                        "related_sectors": sorted(set(rule["positive_sectors"] + rule["negative_sectors"])),
                        "confidence": cls._confidence(rule, sector, stock_name, evidence),
                        "evidence": evidence,
                        "note": rule["note"],
                    }
                )

        themes.sort(key=lambda x: {"high": 3, "medium": 2, "low": 1}.get(x["confidence"], 0), reverse=True)
        themes = themes[:limit]
        return {
            "available": bool(themes),
            "sector": sector,
            "themes": themes,
            "warnings": [] if themes else ["no_relevant_industry_event_match"],
            "note": "社会/政策/行业新闻仅作为行业影响线索，不能等同于个股事实或公司公告。",
        }

    @classmethod
    def filter_market_news(cls, rows: list[Any], limit: int = 80) -> list[dict[str, Any]]:
        items = []
        seen = set()
        for row in rows:
            item = cls._row_to_item(row)
            title = item.get("title", "").strip()
            if not title or title in seen:
                continue
            text = cls._text(item)
            if item.get("related_sector") or item.get("event_category") in ("政策", "市场") or any(k in text for k in cls.MARKET_WIDE_KEYWORDS):
                seen.add(title)
                items.append(item)
            if len(items) >= limit:
                break
        return items

    @staticmethod
    def _row_to_item(row: Any) -> dict[str, Any]:
        if isinstance(row, dict):
            return dict(row)
        publish_time = getattr(row, "publish_time", None)
        if isinstance(publish_time, datetime):
            publish_time = publish_time.isoformat()
        return {
            "title": getattr(row, "title", "") or "",
            "stock_symbol": getattr(row, "stock_symbol", "") or "",
            "summary": getattr(row, "summary", "") or "",
            "source": getattr(row, "source", "") or "",
            "url": getattr(row, "url", "") or "",
            "publish_time": publish_time or "",
            "sentiment": getattr(row, "sentiment", "") or "",
            "sentiment_score": getattr(row, "sentiment_score", 0) or 0,
            "impact_level": getattr(row, "impact_level", "") or "",
            "event_category": getattr(row, "event_category", "") or "",
            "related_sector": getattr(row, "related_sector", "") or "",
        }

    @staticmethod
    def _text(item: dict[str, Any]) -> str:
        return f"{item.get('title', '')} {item.get('summary', '')} {item.get('related_sector', '')}"

    @staticmethod
    def _news_matches_rule(text: str, rule: dict[str, Any]) -> bool:
        return any(keyword in text for keyword in rule["keywords"])

    @classmethod
    def _is_relevant_to_stock(cls, rule: dict[str, Any], item: dict[str, Any], sector: str, stock_name: str, text: str) -> bool:
        related = f"{item.get('related_sector', '')} {sector} {stock_name} {text}"
        sectors = rule["positive_sectors"] + rule["negative_sectors"]
        if any(sec and sec in related for sec in sectors):
            return True
        if not sector:
            return bool(stock_name and stock_name in text and any(keyword in text for keyword in rule["keywords"]))
        return False

    @staticmethod
    def _direction_for_sector(rule: dict[str, Any], sector: str, stock_name: str) -> str:
        target = f"{sector} {stock_name}"
        if any(sec and sec in target for sec in rule["negative_sectors"]):
            return "negative"
        if any(sec and sec in target for sec in rule["positive_sectors"]):
            return "positive" if rule["direction"] != "mixed" else "positive_or_mixed"
        return rule["direction"]

    @staticmethod
    def _confidence(rule: dict[str, Any], sector: str, stock_name: str, evidence: list[dict[str, Any]]) -> str:
        target = f"{sector} {stock_name}"
        if any(sec and sec in target for sec in rule["positive_sectors"] + rule["negative_sectors"]):
            return "high" if len(evidence) >= 2 else "medium"
        return "low"

    @staticmethod
    def _evidence(item: dict[str, Any]) -> dict[str, str]:
        stock_symbol = str(item.get("stock_symbol", "") or "")
        return {
            "title": str(item.get("title", ""))[:120],
            "source": str(item.get("source", ""))[:40],
            "publish_time": str(item.get("publish_time", ""))[:30],
            "related_sector": str(item.get("related_sector", ""))[:60],
            "scope": "market_news" if not stock_symbol else "stock_news_theme",
        }
