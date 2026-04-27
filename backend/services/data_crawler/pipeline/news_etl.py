"""
新闻情感 ETL — 去重 + 情感标记 + 事件分类 + 入库
"""
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ── 金融情感词典 ──
POSITIVE_PATTERNS = [
    (r"(?:连续\s*)?涨停", 0.9), (r"(?:大额\s*)?增持", 0.7), (r"回购(?:股份)?", 0.6),
    (r"业绩(?:大幅\s*)?预增", 0.8), (r"(?:签订\s*)?重大合同", 0.7), (r"中标", 0.6),
    (r"利好", 0.6), (r"扭亏(?:为盈)?", 0.7), (r"高速增长", 0.7), (r"超预期", 0.8),
    (r"新产品发布", 0.5), (r"重大项目", 0.6), (r"战略合作", 0.6), (r"机构增持", 0.5),
    (r"目标价上调", 0.7), (r"高分红", 0.5), (r"高送转", 0.5), (r"员工持股", 0.4),
    (r"股权激励", 0.5), (r"收购", 0.6), (r"重组获批", 0.7), (r"获得资质", 0.5),
    (r"获批复", 0.5), (r"业绩稳健", 0.4), (r"订单增长", 0.5), (r"产能释放", 0.4),
    (r"技术突破", 0.6), (r"创新药.*获批", 0.8), (r"(?:成功\s*)?上市", 0.5),
    (r"(?:行业\s*)?龙头", 0.4), (r"市场份额.*提升", 0.5), (r"毛利.*?提升", 0.5),
    (r"研发投入", 0.3), (r"拿到批文", 0.7), (r"量价齐升", 0.7), (r"供不应求", 0.6),
]
NEGATIVE_PATTERNS = [
    (r"(?:连续\s*)?跌停", -0.9), (r"(?:大额\s*)?减持", -0.7), (r"业绩(?:大幅\s*)?预亏", -0.8),
    (r"亏损", -0.6), (r"处罚", -0.7), (r"立案(?:调查)?", -0.9), (r"退市风险", -0.95),
    (r"利空", -0.6), (r"(?:大幅\s*)?下滑", -0.6), (r"不及预期", -0.7), (r"诉讼", -0.5),
    (r"仲裁", -0.4), (r"(?:限售\s*)?解禁", -0.5), (r"ST", -0.8), (r"债务违约", -0.9),
    (r"资产减值", -0.7), (r"商誉减值", -0.9), (r"资金冻结", -0.8), (r"大股东质押", -0.5),
    (r"被调查", -0.8), (r"业绩(?:大幅\s*)?修正", -0.6), (r"终止重组", -0.8), (r"停产", -0.7),
    (r"重组失败", -0.8), (r"被ST", -0.9), (r"收到问询函", -0.5), (r"收到监管函", -0.6),
    (r"高管.*辞职", -0.4), (r"信披违规", -0.7), (r"涉嫌操纵", -0.9), (r"财务造假", -0.95),
    (r"净利润.*?下滑", -0.5), (r"营收.*?下滑", -0.5), (r"毛利率.*?下降", -0.5),
    (r"订单.*?减少", -0.5), (r"产能过剩", -0.4), (r"价格战", -0.4),
]

SOURCE_AUTHORITY = {
    "证监会": 1.0, "沪深交易所": 1.0, "深交所": 1.0, "上交所": 1.0,
    "央行": 0.95, "银保监会": 0.95, "国务院": 0.95, "发改委": 0.9,
    "财联社": 0.8, "证券时报": 0.8, "上海证券报": 0.8, "中国证券报": 0.8,
    "东方财富": 0.55, "新浪财经": 0.5, "网易财经": 0.5, "搜狐财经": 0.5,
    "同花顺": 0.55, "雪球": 0.4, "其他": 0.35,
}

EVENT_CATEGORY_RULES = [
    ("经营", [r"业绩", r"营收", r"净利润", r"合同", r"中标", r"订单", r"产品",
              r"毛利率", r"产能", r"停产", r"复工"]),
    ("政策", [r"政策", r"补贴", r"监管", r"发改委", r"国务院", r"工信部",
              r"央行", r"税率", r"关税", r"环保"]),
    ("市场", [r"减持", r"增持", r"回购", r"解禁", r"质押", r"分红",
              r"送转", r"股权", r"定向增发"]),
    ("舆论", [r"研报", r"评级", r"目标价", r"媒体", r"曝光", r"维权"]),
]


class NewsETL:
    """新闻ETL: 去重 → 关键词提取 → 情感标记 → 事件分类 → 入库"""

    def compute_sentiment(self, title: str, summary: str = "") -> tuple:
        """
        基于金融词典规则计算情感得分
        返回: (sentiment_label, sentiment_score, impact_level)
        """
        text = f"{title} {summary}"
        score = 0.0
        matched = 0

        for pattern, weight in POSITIVE_PATTERNS:
            if re.search(pattern, text):
                score += weight
                matched += 1
        for pattern, weight in NEGATIVE_PATTERNS:
            if re.search(pattern, text):
                score += weight
                matched += 1

        if matched > 0:
            score = max(-1.0, min(1.0, score / max(matched, 1)))
        else:
            score = 0.0

        if score >= 0.3:
            label = "正面"
        elif score <= -0.3:
            label = "负面"
        else:
            label = "中性"

        return label, round(score, 3), self._impact_level(abs(score), title)

    def _impact_level(self, abs_score: float, title: str) -> str:
        if abs_score >= 0.7:
            return "高"
        elif abs_score >= 0.4:
            return "中"
        return "低"

    def classify_event(self, title: str, summary: str = "") -> Optional[str]:
        text = f"{title} {summary}"
        for category, patterns in EVENT_CATEGORY_RULES:
            for pat in patterns:
                if re.search(pat, text):
                    return category
        return None

    def extract_keywords(self, title: str) -> list:
        words = []
        for kw in ["业绩", "减持", "增持", "回购", "重组", "解禁", "分红", "涨停",
                    "跌停", "中标", "合同", "订单", "新品", "获批", "处罚", "立案",
                    "预增", "预亏", "扭亏", "ST", "退市", "政策", "补贴", "监管"]:
            if kw in title:
                words.append(kw)
        return words[:8]

    def _normalize_time(self, raw) -> Optional[datetime]:
        if not raw:
            return datetime.now(timezone.utc)
        raw = str(raw).strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                     "%Y-%m-%d", "%Y%m%d", "%Y/%m/%d %H:%M:%S",
                     "%m月%d日 %H:%M", "%m-%d %H:%M", "%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(raw, fmt)
            except ValueError:
                continue
        # 尝试解析相对时间 (如 "3分钟前", "1小时前")
        rel_match = re.match(r"(\d+)\s*(分钟|小时)前", raw)
        if rel_match:
            n = int(rel_match.group(1))
            unit = rel_match.group(2)
            now = datetime.now()
            if unit == "分钟":
                return now - timedelta(minutes=n)
            else:
                return now - timedelta(hours=n)
        return datetime.now(timezone.utc)

    def _compute_freshness(self, publish_time: datetime) -> str:
        now = datetime.now()
        delta = now - publish_time.replace(tzinfo=None)
        if delta < timedelta(hours=1):
            return "realtime"
        elif delta < timedelta(hours=24):
            return "today"
        elif delta < timedelta(days=7):
            return "within_week"
        return "historical"

    def clean(self, symbol: str, raw_items: list[dict]) -> list[dict]:
        cleaned = []
        for item in raw_items:
            title = item.get("title", "")
            if not title or len(title) < 4:
                continue
            publish_time = self._normalize_time(item.get("publish_time", ""))
            sentiment_label, sentiment_score, impact = self.compute_sentiment(
                title, item.get("summary", "")
            )
            cleaned.append({
                "stock_symbol": symbol[:6],
                "title": title[:500],
                "summary": (item.get("summary", "") or "")[:2000],
                "source": item.get("source", "未知")[:100],
                "url": (item.get("url", "") or "")[:500],
                "publish_time": publish_time,
                "sentiment": sentiment_label,
                "sentiment_score": sentiment_score,
                "impact_level": impact,
                "event_category": self.classify_event(title, item.get("summary", "")),
                "related_sector": item.get("related_sector", ""),
                "keywords": self.extract_keywords(title),
                "freshness": self._compute_freshness(publish_time),
            })
        return cleaned

    async def save(self, db_session, symbol: str, raw_items: list[dict]) -> int:
        from backend.shared.models import StockNews
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        cleaned = self.clean(symbol, raw_items)
        if not cleaned:
            return 0

        # 清除 freshness 字段，它不在 ORM 中
        saved = 0
        for row in cleaned:
            row.pop("freshness", None)
            try:
                stmt = sqlite_insert(StockNews).values(**row).on_conflict_do_nothing()
                db_session.execute(stmt)
                saved += 1
            except Exception as e:
                logger.debug(f"[{symbol}] 新闻入库跳过: {e}")
        db_session.commit()
        logger.info(f"[{symbol}] 新闻入库: {saved}/{len(cleaned)} 条 (正面:{sum(1 for r in cleaned if r['sentiment']=='正面')}, 负面:{sum(1 for r in cleaned if r['sentiment']=='负面')})")
        return saved
