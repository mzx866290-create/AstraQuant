"""
公告与财报 ETL 管道 — 清洗 + 衍生指标计算 + 入库
"""
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class AnnouncementETL:
    """公告数据ETL: 清洗 -> 去重 -> 入库"""

    DATE_COLUMNS = ["公告日期", "date", "ann_date", "notice_date", "declaredate"]
    TITLE_COLUMNS = ["标题", "title", "notice_title", "name"]
    SUMMARY_COLUMNS = ["内容摘要", "summary", "content_desc"]
    URL_COLUMNS = ["公告链接", "url", "pdf_url", "notice_url"]
    CATEGORY_COLUMNS = ["分类", "category", "type", "notice_type"]

    def _find_field(self, item: dict, keys: list, default=""):
        for k in keys:
            val = item.get(k, "")
            if val:
                return str(val)
        return default

    def _classify(self, title: str) -> str:
        t = title.lower()
        if any(w in t for w in ["季报", "年报", "中报", "半年报", "年度报告", "季度报告", "第一季度", "第二季度", "第三季度", "第四季度"]):
            return "定期报告"
        if any(w in t for w in ["业绩预告", "业绩快报", "预增", "预减", "预亏", "预盈"]):
            return "业绩预告"
        if any(w in t for w in ["分红", "送转", "派息", "转增", "除权"]):
            return "分红送转"
        if any(w in t for w in ["减持", "增持", "回购", "股权", "解禁", "质押"]):
            return "股东变动"
        if any(w in t for w in ["重组", "收购", "并购", "重大资产", "定向增发"]):
            return "重大事项"
        return "临时公告"

    def _normalize_date(self, raw: str) -> Optional[datetime]:
        if not raw:
            return None
        raw = str(raw).strip()
        for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d", "%m/%d/%Y"):
            try:
                return datetime.strptime(raw[:10], fmt)
            except ValueError:
                continue
        return None

    def clean(self, symbol: str, raw_items: list[dict], source: str) -> list[dict]:
        cleaned = []
        for item in raw_items:
            title = self._find_field(item, self.TITLE_COLUMNS)
            if not title or len(title) < 4:
                continue
            announce_date = self._normalize_date(
                self._find_field(item, self.DATE_COLUMNS)
            )
            if not announce_date:
                continue
            cleaned.append({
                "stock_symbol": symbol[:6],
                "title": title[:500],
                "summary": self._find_field(item, self.SUMMARY_COLUMNS)[:2000],
                "content_url": self._find_field(item, self.URL_COLUMNS)[:500],
                "announce_date": announce_date,
                "source": source,
                "category": self._classify(title),
            })
        return cleaned

    async def save(self, db_session, symbol: str, raw_items: list[dict], source: str):
        from backend.shared.models import CompanyAnnouncement
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        cleaned = self.clean(symbol, raw_items, source)
        if not cleaned:
            logger.warning(f"[{symbol}] 无有效公告数据")
            return 0

        saved = 0
        for row in cleaned:
            try:
                stmt = sqlite_insert(CompanyAnnouncement).values(**row).on_conflict_do_nothing()
                db_session.execute(stmt)
                saved += 1
            except Exception as e:
                logger.debug(f"[{symbol}] 公告入库跳过 (可能重复): {e}")
        db_session.commit()
        logger.info(f"[{symbol}] 公告入库完成: {saved}/{len(cleaned)} 条")
        return saved


class FinancialReportETL:
    """财报ETL: 三表合并 -> 关键指标提取 -> 衍生比率计算 -> 入库"""

    REQUIRED_KEYS = {
        "balance": ["total_assets", "total_liabilities", "total_equity",
                     "current_assets", "current_liabilities"],
        "profit": ["revenue", "net_profit", "gross_margin", "net_margin", "eps"],
        "cashflow": ["operating_cf", "investing_cf", "financing_cf"],
    }

    def _safe_float(self, val) -> Optional[float]:
        if val is None:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    def _determine_report_type(self, date_str: str) -> str:
        """根据月份判断报告类型"""
        try:
            month = int(date_str[5:7]) if "-" in date_str else int(date_str[4:6])
        except (ValueError, IndexError):
            return "年报"
        if month == 3:
            return "一季报"
        elif month == 6:
            return "中报"
        elif month == 9:
            return "三季报"
        elif month == 12:
            return "年报"
        return "年报"

    def _normalize_date(self, raw) -> Optional[datetime]:
        if not raw:
            return None
        raw = str(raw).strip()
        for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d"):
            try:
                return datetime.strptime(raw[:10], fmt)
            except ValueError:
                continue
        return None

    def merge_and_compute(
        self,
        symbol: str,
        balance_data: list[dict],
        profit_data: list[dict],
        cashflow_data: list[dict],
        source: str = "akshare",
    ) -> list[dict]:
        """三表合并，按报告期对齐，计算衍生指标"""
        # 按报告期建立索引
        profit_by_date = {}
        for item in profit_data:
            d = str(item.get("报告期", item.get("report_date", item.get("date", ""))))[:10]
            if d:
                profit_by_date[d] = item

        balance_by_date = {}
        for item in balance_data:
            d = str(item.get("报告期", item.get("report_date", item.get("date", ""))))[:10]
            if d:
                balance_by_date[d] = item

        cashflow_by_date = {}
        for item in cashflow_data:
            d = str(item.get("报告期", item.get("report_date", item.get("date", ""))))[:10]
            if d:
                cashflow_by_date[d] = item

        all_dates = set(profit_by_date.keys()) | set(balance_by_date.keys())
        if not all_dates:
            return []

        results = []
        for date_str in sorted(all_dates, reverse=True):
            report_date = self._normalize_date(date_str)
            if not report_date:
                continue

            b = balance_by_date.get(date_str, {})
            p = profit_by_date.get(date_str, {})
            c = cashflow_by_date.get(date_str, {})

            # 核心指标提取
            total_assets = self._safe_float(b.get("资产总计", b.get("total_assets")))
            total_liabilities = self._safe_float(b.get("负债合计", b.get("total_liabilities")))
            total_equity = self._safe_float(
                b.get("归属于母公司股东权益合计", b.get("股东权益合计", b.get("total_equity")))
            )
            current_assets = self._safe_float(b.get("流动资产合计", b.get("current_assets")))
            current_liabilities = self._safe_float(b.get("流动负债合计", b.get("current_liabilities")))

            revenue = self._safe_float(p.get("营业总收入", p.get("营业收入", p.get("revenue"))))
            net_profit = self._safe_float(
                p.get("归属于母公司股东的净利润", p.get("净利润", p.get("net_profit")))
            )
            gross_margin = self._safe_float(p.get("毛利率", p.get("gross_margin")))
            net_margin = self._safe_float(p.get("净利率", p.get("net_margin")))
            eps = self._safe_float(p.get("基本每股收益", p.get("eps")))

            # 同比增速从AKShare财务摘要中获取
            revenue_yoy = self._safe_float(p.get("营业收入同比", p.get("revenue_yoy")))
            net_profit_yoy = self._safe_float(p.get("净利润同比", p.get("net_profit_yoy")))

            operating_cf = self._safe_float(
                c.get("经营活动产生的现金流量净额", c.get("operating_cf"))
            )
            investing_cf = self._safe_float(
                c.get("投资活动产生的现金流量净额", c.get("investing_cf"))
            )
            financing_cf = self._safe_float(
                c.get("筹资活动产生的现金流量净额", c.get("financing_cf"))
            )

            # 衍生指标计算
            roe = None
            if net_profit is not None and total_equity is not None and total_equity != 0:
                roe = round(net_profit / total_equity * 100, 2)

            roa = None
            if net_profit is not None and total_assets is not None and total_assets != 0:
                roa = round(net_profit / total_assets * 100, 2)

            bvps = None
            if total_equity is not None:
                bvps = round(total_equity / 1e8, 4)

            results.append({
                "stock_symbol": symbol[:6],
                "report_date": report_date,
                "report_type": self._determine_report_type(date_str),
                "total_assets": total_assets,
                "total_liabilities": total_liabilities,
                "total_equity": total_equity,
                "current_assets": current_assets,
                "current_liabilities": current_liabilities,
                "revenue": revenue,
                "revenue_yoy": revenue_yoy,
                "net_profit": net_profit,
                "net_profit_yoy": net_profit_yoy,
                "gross_margin": gross_margin,
                "net_margin": net_margin,
                "eps": eps,
                "bvps": bvps,
                "roe": roe,
                "roa": roa,
                "operating_cf": operating_cf,
                "investing_cf": investing_cf,
                "financing_cf": financing_cf,
                "pe_ttm": None,
                "pb": None,
                "source": source,
            })

        return results

    async def save(
        self,
        db_session,
        symbol: str,
        balance_data: list[dict],
        profit_data: list[dict],
        cashflow_data: list[dict],
        source: str = "akshare",
    ) -> int:
        from backend.shared.models import FinancialReport
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        merged = self.merge_and_compute(symbol, balance_data, profit_data, cashflow_data, source)
        if not merged:
            logger.warning(f"[{symbol}] 无有效财报数据")
            return 0

        saved = 0
        for row in merged:
            try:
                stmt = sqlite_insert(FinancialReport).values(**row).on_conflict_do_nothing()
                db_session.execute(stmt)
                saved += 1
            except Exception as e:
                logger.debug(f"[{symbol}] 财报入库跳过: {e}")
        db_session.commit()
        logger.info(f"[{symbol}] 财报入库完成: {saved}/{len(merged)} 条")
        return saved
