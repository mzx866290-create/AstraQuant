"""
来源追溯系统 — 数据来源引用 / 事实核查 / 新鲜度评估
"""
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional


@dataclass
class SourceCitation:
    source_name: str       # "EastMoney" / "AKShare" / "ClickHouse"
    data_type: str         # "kline" / "financial_report" / "announcement" / "news" / "money_flow"
    fetch_time: str        # ISO 8601
    freshness: str         # "realtime" / "today" / "within_week" / "within_month" / "historical"
    url: Optional[str] = None
    record_count: Optional[int] = None


class SourceAttributionManager:
    """管理分析中所有数据来源，生成引用块和新鲜度报告"""

    def __init__(self):
        self.citations: list[SourceCitation] = []
        self.warnings: list[str] = []

    def add(self, source_name: str, data_type: str, fetch_time: Optional[datetime] = None,
            url: str = None, record_count: int = None):
        if fetch_time is None:
            fetch_time = datetime.now(timezone.utc)
        freshness = self._compute_freshness(fetch_time)
        self.citations.append(SourceCitation(
            source_name=source_name,
            data_type=data_type,
            fetch_time=fetch_time.isoformat() if isinstance(fetch_time, datetime) else str(fetch_time),
            freshness=freshness,
            url=url,
            record_count=record_count,
        ))
        if freshness in ("historical",):
            self.warnings.append(f"{data_type}数据较旧 ({freshness})，来源: {source_name}")

    @staticmethod
    def _compute_freshness(fetch_time: datetime) -> str:
        if fetch_time.tzinfo:
            fetch_time = fetch_time.replace(tzinfo=None)
        delta = datetime.now() - fetch_time
        if delta < timedelta(minutes=5):
            return "realtime"
        elif delta < timedelta(hours=24):
            return "today"
        elif delta < timedelta(days=7):
            return "within_week"
        elif delta < timedelta(days=30):
            return "within_month"
        return "historical"

    def build_citation_block(self) -> str:
        """构建Markdown格式的数据来源块"""
        if not self.citations:
            return "\n> 数据来源: 无记录\n"

        lines = ["\n## 数据来源\n"]
        seen = set()
        for i, c in enumerate(self.citations, 1):
            key = (c.data_type, c.source_name)
            if key in seen:
                continue
            seen.add(key)
            freshness_icon = {"realtime": "🟢", "today": "🟢", "within_week": "🟡",
                            "within_month": "🟠", "historical": "🔴"}.get(c.freshness, "⚪")
            rec = f" ({c.record_count}条)" if c.record_count else ""
            lines.append(
                f"{i}. {freshness_icon} **{c.data_type}**: {c.source_name}"
                f" (更新时间: {c.fetch_time[:16]}, 新鲜度: {c.freshness}){rec}"
            )

        if self.warnings:
            lines.append("\n### 数据质量提示\n")
            for w in self.warnings:
                lines.append(f"-  {w}")

        return "\n".join(lines)

    def build_freshness_summary(self) -> str:
        """数据新鲜度总结"""
        if not self.citations:
            return "无数据"
        statuses = [c.freshness for c in self.citations]
        if all(s in ("realtime", "today") for s in statuses):
            return "数据新鲜 (全部24小时内)"
        elif any(s == "historical" for s in statuses):
            return "部分数据较旧 (财报来自上期报告)"
        return "数据较新 (大部分在7天内)"

    def validate_claim(self, claim: str, source_data: dict) -> dict:
        """事实验证：提取AI分析中的数值主张，与源数据交叉比对"""
        warnings = []
        # 匹配模式: "PE为30倍" / "ROE达15.3%" / "营收500亿"
        patterns = [
            (r'PE[为达约]*\s*(\d+\.?\d*)\s*倍', 'pe_ttm', 5),
            (r'PB[为达约]*\s*(\d+\.?\d*)\s*倍', 'pb', 5),
            (r'ROE[为达约]*\s*(\d+\.?\d*)\s*%', 'roe', 5),
            (r'营收[为达约]*\s*(\d+\.?\d*)\s*亿', 'revenue', 10),
            (r'净利润[为达约]*\s*(\d+\.?\d*)\s*亿', 'net_profit', 10),
            (r'毛利率[为达约]*\s*(\d+\.?\d*)\s*%', 'gross_margin', 3),
            (r'净利率[为达约]*\s*(\d+\.?\d*)\s*%', 'net_margin', 3),
            (r'涨跌幅[为达约]*\s*([+-]?\d+\.?\d*)\s*%', 'change_pct', 2),
        ]

        for pattern, key, tolerance in patterns:
            match = re.search(pattern, claim)
            if match:
                ai_value = float(match.group(1))
                actual = source_data.get(key)
                if actual is not None:
                    diff_pct = abs(ai_value - actual) / max(abs(actual), 0.01) * 100
                    if diff_pct > tolerance:
                        warnings.append({
                            "claim": match.group(0),
                            "ai_value": ai_value,
                            "actual_value": actual,
                            "diff_pct": round(diff_pct, 1),
                            "key": key,
                            "tolerance": tolerance,
                        })

        return {
            "verified": len(warnings) == 0,
            "claims_checked": len([m for p, _, _ in patterns for m in [re.search(p, claim)] if m]),
            "warnings": warnings,
            "severity": "high" if any(w["diff_pct"] > 20 for w in warnings) else "low" if warnings else "none",
        }
