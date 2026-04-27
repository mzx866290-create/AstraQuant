"""
新闻情感分析引擎 — 事件分类 / 影响力评分 / 历史影响推演 / 情感汇总
"""
from datetime import datetime, timedelta
from typing import Optional


class NewsSentimentEngine:

    # ── 来源权威性 ──
    SOURCE_AUTHORITY = {
        "证监会": 1.0, "上交所": 0.95, "深交所": 0.95, "央行": 0.95,
        "国务院": 0.95, "银保监会": 0.95, "发改委": 0.9, "工信部": 0.85,
        "财联社": 0.7, "证券时报": 0.75, "上海证券报": 0.75, "中国证券报": 0.75,
        "21世纪经济报道": 0.65, "第一财经": 0.65, "界面新闻": 0.55,
        "东方财富": 0.5, "新浪财经": 0.45, "网易财经": 0.45,
        "同花顺": 0.5, "雪球": 0.35, "未知": 0.3,
    }

    # ── 影响力基准 (同类事件的历史平均涨跌幅) ──
    IMPACT_BENCHMARK = {
        ("业绩", "预增"): {"direction": "正面", "avg_1d": 2.5, "avg_5d": 4.0, "avg_20d": 6.0, "count": 1200},
        ("业绩", "预亏"): {"direction": "负面", "avg_1d": -3.0, "avg_5d": -5.0, "avg_20d": -7.0, "count": 800},
        ("业绩", "超预期"): {"direction": "正面", "avg_1d": 3.5, "avg_5d": 6.0, "avg_20d": 9.0, "count": 600},
        ("减持", "大股东"): {"direction": "负面", "avg_1d": -2.0, "avg_5d": -3.5, "avg_20d": -4.0, "count": 1500},
        ("增持", "大股东"): {"direction": "正面", "avg_1d": 1.5, "avg_5d": 3.0, "avg_20d": 5.0, "count": 900},
        ("回购", ""): {"direction": "正面", "avg_1d": 1.0, "avg_5d": 2.0, "avg_20d": 3.5, "count": 700},
        ("重组", ""): {"direction": "正面", "avg_1d": 5.0, "avg_5d": 8.0, "avg_20d": 12.0, "count": 300},
        ("重组失败", ""): {"direction": "负面", "avg_1d": -5.0, "avg_5d": -8.0, "avg_20d": -6.0, "count": 150},
        ("立案", ""): {"direction": "负面", "avg_1d": -5.0, "avg_5d": -10.0, "avg_20d": -15.0, "count": 200},
        ("退市", ""): {"direction": "负面", "avg_1d": -5.0, "avg_5d": -15.0, "avg_20d": -25.0, "count": 50},
        ("中标", ""): {"direction": "正面", "avg_1d": 1.5, "avg_5d": 3.0, "avg_20d": 4.0, "count": 500},
        ("合同", ""): {"direction": "正面", "avg_1d": 1.0, "avg_5d": 2.0, "avg_20d": 3.0, "count": 800},
        ("政策", "扶持"): {"direction": "正面", "avg_1d": 2.0, "avg_5d": 4.0, "avg_20d": 7.0, "count": 400},
        ("解禁", ""): {"direction": "负面", "avg_1d": -1.5, "avg_5d": -3.0, "avg_20d": -3.5, "count": 1000},
    }

    @staticmethod
    def match_benchmark(title: str) -> Optional[dict]:
        for (key1, key2), benchmark in NewsSentimentEngine.IMPACT_BENCHMARK.items():
            if key1 in title and (not key2 or key2 in title):
                return benchmark
        return None

    @staticmethod
    def predict_impact(title: str, sentiment_score: float, source_name: str) -> dict:
        """基于历史相似事件预测个股影响"""
        benchmark = NewsSentimentEngine.match_benchmark(title)
        authority = NewsSentimentEngine.SOURCE_AUTHORITY.get(source_name, 0.3)

        if benchmark:
            confidence = min(90, benchmark["count"] / 10)  # 样本越多置信度越高
            base_1d = benchmark["avg_1d"]
            base_5d = benchmark["avg_5d"]
            base_20d = benchmark["avg_20d"]
        else:
            confidence = 30
            # 按情感得分估算
            base_1d = sentiment_score * 3.0
            base_5d = sentiment_score * 5.0
            base_20d = sentiment_score * 8.0

        # 权威性调整
        auth_adj = 0.5 + authority * 0.5  # 0.65-1.0

        return {
            "direction": "正面" if base_1d >= 0 else "负面",
            "impact_1d_pct": round(base_1d * auth_adj, 2),
            "impact_5d_pct": round(base_5d * auth_adj, 2),
            "impact_20d_pct": round(base_20d * auth_adj, 2),
            "confidence": round(min(90, confidence * auth_adj), 0),
            "has_benchmark": benchmark is not None,
            "source_authority": authority,
            "note": "" if benchmark else "无历史基准，基于情感得分估算",
        }

    @staticmethod
    def compute_influence_score(
        sentiment_score: float,
        impact_level: str,
        source_name: str,
        freshness_hours: float,
    ) -> float:
        """综合影响力评分 (0-10)"""
        authority = NewsSentimentEngine.SOURCE_AUTHORITY.get(source_name, 0.3)

        # 基础分：情感强度
        base = abs(sentiment_score) * 5.0

        # 影响力等级加成
        impact_bonus = {"高": 3.0, "中": 1.5, "低": 0.0}.get(impact_level, 0)

        # 时效性衰减
        if freshness_hours <= 1:
            time_factor = 1.0
        elif freshness_hours <= 4:
            time_factor = 0.9
        elif freshness_hours <= 24:
            time_factor = 0.7
        elif freshness_hours <= 72:
            time_factor = 0.4
        else:
            time_factor = 0.2

        # 权威性加权
        score = (base + impact_bonus) * authority * time_factor
        return round(min(10.0, score), 1)

    @staticmethod
    def summarize_sentiment(news_list: list[dict], days: int = 7) -> dict:
        """汇总一段时间内的新闻情感"""
        if not news_list:
            return {"total": 0, "positive": 0, "negative": 0, "neutral": 0,
                    "avg_score": 0, "dominant_sentiment": "无数据",
                    "top_impact": [], "trend": "无数据"}

        # Parse publish_time for all items once
        now = datetime.now()
        for n in news_list:
            pt = n.get("publish_time", now)
            if isinstance(pt, str):
                try:
                    pt = datetime.fromisoformat(pt.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    pt = now
            if hasattr(pt, 'tzinfo') and pt.tzinfo is not None:
                pt = pt.replace(tzinfo=None)
            n["_parsed_time"] = pt

        cutoff = now - timedelta(days=days)
        recent = [n for n in news_list if n["_parsed_time"] >= cutoff]

        if not recent:
            return {"total": 0, "positive": 0, "negative": 0, "neutral": 0,
                    "avg_score": 0, "dominant_sentiment": "近{days}天无新闻",
                    "top_impact": [], "trend": "无数据"}

        pos = sum(1 for n in recent if n.get("sentiment") == "正面")
        neg = sum(1 for n in recent if n.get("sentiment") == "负面")
        neu = sum(1 for n in recent if n.get("sentiment") == "中性")
        scores = [n.get("sentiment_score", 0) for n in recent]

        # 按影响力排序取Top5 (清理内部字段)
        sorted_by_impact = sorted(
            recent, key=lambda n: abs(n.get("sentiment_score", 0)), reverse=True
        )[:5]
        top_impact_clean = [
            {k: v for k, v in item.items() if k != "_parsed_time"}
            for item in sorted_by_impact
        ]

        # 趋势：最近24小时 vs 前3天的情感对比
        recent_24h = [n for n in recent if n["_parsed_time"] >= now - timedelta(hours=24)]
        older_72h = [n for n in recent if n["_parsed_time"] < now - timedelta(hours=24)]

        if recent_24h and older_72h:
            avg_24h = sum(n.get("sentiment_score", 0) for n in recent_24h) / len(recent_24h)
            avg_72h = sum(n.get("sentiment_score", 0) for n in older_72h) / len(older_72h)
            if avg_24h > avg_72h + 0.1:
                trend = "改善 ↑"
            elif avg_24h < avg_72h - 0.1:
                trend = "恶化 ↓"
            else:
                trend = "平稳 →"
        else:
            trend = "数据不足"

        dominant = "正面" if pos >= neg and pos >= neu else "负面" if neg >= pos else "中性"

        return {
            "total": len(recent),
            "positive": pos,
            "negative": neg,
            "neutral": neu,
            "positive_ratio": round(pos / len(recent) * 100, 1),
            "negative_ratio": round(neg / len(recent) * 100, 1),
            "avg_score": round(sum(scores) / len(scores), 3) if scores else 0,
            "dominant_sentiment": dominant,
            "top_impact": top_impact_clean,
            "trend": trend,
        }
