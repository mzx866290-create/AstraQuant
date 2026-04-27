"""
专业财务分析引擎 — 杜邦分析 / Piotroski F-Score / Altman Z-Score / PE-PB Band
"""
import math
from typing import Optional


class FinancialAnalysisEngine:

    # ── 杜邦分析 ──

    @staticmethod
    def dupont_decomposition(
        net_margin: Optional[float],
        asset_turnover: Optional[float],
        equity_multiplier: Optional[float],
    ) -> dict:
        """杜邦分解: ROE = 净利率 x 总资产周转率 x 权益乘数"""

        roe = None
        if all(v is not None for v in [net_margin, asset_turnover, equity_multiplier]):
            roe = round(net_margin * asset_turnover * equity_multiplier, 2)

        return {
            "roe": roe,
            "net_margin": net_margin,
            "asset_turnover": asset_turnover,
            "equity_multiplier": equity_multiplier,
            "interpretation": FinancialAnalysisEngine._dupont_interpretation(
                net_margin, asset_turnover, equity_multiplier
            ),
        }

    @staticmethod
    def dupont_from_reports(reports: list[dict]) -> dict:
        """从最新财务报告计算杜邦分解"""
        if not reports:
            return {"roe": None, "net_margin": None, "asset_turnover": None,
                    "equity_multiplier": None, "interpretation": "无数据"}

        latest = reports[0]
        net_margin = latest.get("net_margin")
        if net_margin is not None and net_margin > 1:  # 百分比转小数
            net_margin = net_margin / 100

        revenue = latest.get("revenue")
        total_assets = latest.get("total_assets")
        asset_turnover = None
        if revenue and total_assets and total_assets != 0:
            asset_turnover = round(revenue / total_assets, 4)

        total_assets_val = latest.get("total_assets")
        total_equity = latest.get("total_equity")
        equity_multiplier = None
        if total_assets_val and total_equity and total_equity != 0:
            equity_multiplier = round(total_assets_val / total_equity, 4)

        return FinancialAnalysisEngine.dupont_decomposition(
            net_margin, asset_turnover, equity_multiplier
        )

    @staticmethod
    def _dupont_interpretation(nm, at, em) -> str:
        if any(v is None for v in [nm, at, em]):
            return "数据不完整，无法解读"
        drivers = []
        if nm and nm > 0.15:
            drivers.append("高利润率驱动型（产品竞争力强）")
        elif nm and nm < 0.05:
            drivers.append("低利润率运营（薄利多销或成本控制弱）")

        if at and at > 1.0:
            drivers.append("高周转型（资产使用效率高）")
        elif at and at < 0.3:
            drivers.append("低周转型（重资产或资产闲置）")

        if em and em > 3.0:
            drivers.append("高杠杆运营（财务风险较大）")
        elif em and em < 1.5:
            drivers.append("低杠杆运营（财务保守）")

        if not drivers:
            return "均衡型经营模式"
        return "；".join(drivers)

    # ── Piotroski F-Score ──

    @staticmethod
    def piotroski_f_score(reports: list[dict]) -> dict:
        """Piotroski F-Score (0-9): 基于最近两期报告对比"""
        if len(reports) < 2:
            return {"score": 0, "details": [], "rating": "数据不足",
                    "max_score": 9, "explanation": "需要至少两期财报"}

        cur = reports[0]
        prev = reports[1]
        details = []

        # 1. 盈利能力 (Profitability) — 4分
        # 1a. ROA > 0
        roa = cur.get("roa")
        if roa is not None and roa > 0:
            details.append({"criterion": "ROA为正", "passed": True, "score": 1,
                           "reason": f"ROA: {roa}%"})
        else:
            details.append({"criterion": "ROA为正", "passed": False, "score": 0,
                           "reason": f"ROA: {roa}%" if roa else "ROA无数据"})

        # 1b. 经营活动现金流 > 0
        ocf = cur.get("operating_cf")
        if ocf is not None and ocf > 0:
            details.append({"criterion": "经营现金流为正", "passed": True, "score": 1,
                           "reason": f"OCF: {ocf/1e8:.1f}亿"})
        else:
            details.append({"criterion": "经营现金流为正", "passed": False, "score": 0, "reason": ""})

        # 1c. ROA 同比提升
        prev_roa = prev.get("roa")
        if roa is not None and prev_roa is not None and roa > prev_roa:
            details.append({"criterion": "ROA同比提升", "passed": True, "score": 1,
                           "reason": f"{prev_roa}% → {roa}%"})
        else:
            details.append({"criterion": "ROA同比提升", "passed": False, "score": 0, "reason": ""})

        # 1d. OCF > Net Income
        ni = cur.get("net_profit")
        if ocf is not None and ni is not None and ocf > ni:
            details.append({"criterion": "经营现金流>净利润", "passed": True, "score": 1,
                           "reason": "利润含金量高"})
        else:
            details.append({"criterion": "经营现金流>净利润", "passed": False, "score": 0,
                           "reason": "利润含金量不足"})

        # 2. 财务杠杆 (Leverage/Liquidity) — 3分
        # 2a. 长期负债率同比下降
        cur_debt_ratio = None
        prev_debt_ratio = None
        if cur.get("total_liabilities") and cur.get("total_assets"):
            cur_debt_ratio = cur["total_liabilities"] / cur["total_assets"]
        if prev.get("total_liabilities") and prev.get("total_assets"):
            prev_debt_ratio = prev["total_liabilities"] / prev["total_assets"]
        if cur_debt_ratio is not None and prev_debt_ratio is not None and cur_debt_ratio < prev_debt_ratio:
            details.append({"criterion": "负债率同比下降", "passed": True, "score": 1,
                           "reason": f"{prev_debt_ratio*100:.1f}% → {cur_debt_ratio*100:.1f}%"})
        else:
            details.append({"criterion": "负债率同比下降", "passed": False, "score": 0, "reason": ""})

        # 2b. 流动比率同比提升
        cur_cr = prev_cr = None
        if cur.get("current_assets") and cur.get("current_liabilities") and cur["current_liabilities"] != 0:
            cur_cr = cur["current_assets"] / cur["current_liabilities"]
        if prev.get("current_assets") and prev.get("current_liabilities") and prev["current_liabilities"] != 0:
            prev_cr = prev["current_assets"] / prev["current_liabilities"]
        if cur_cr is not None and prev_cr is not None and cur_cr > prev_cr:
            details.append({"criterion": "流动比率同比提升", "passed": True, "score": 1,
                           "reason": f"{prev_cr:.2f} → {cur_cr:.2f}"})
        else:
            details.append({"criterion": "流动比率同比提升", "passed": False, "score": 0, "reason": ""})

        # 2c. 无增发
        # (从财报中无法直接判定，默认通过)
        details.append({"criterion": "未增发股份", "passed": True, "score": 1,
                       "reason": "无增发记录（默认）"})

        # 3. 运营效率 (Operating Efficiency) — 2分
        # 3a. 毛利率同比提升
        cur_gm = cur.get("gross_margin")
        prev_gm = prev.get("gross_margin")
        if cur_gm is not None and prev_gm is not None and cur_gm > prev_gm:
            details.append({"criterion": "毛利率同比提升", "passed": True, "score": 1,
                           "reason": f"{prev_gm}% → {cur_gm}%"})
        else:
            details.append({"criterion": "毛利率同比提升", "passed": False, "score": 0, "reason": ""})

        # 3b. 总资产周转率同比提升
        cur_at = prev_at = None
        if cur.get("revenue") and cur.get("total_assets") and cur["total_assets"] != 0:
            cur_at = cur["revenue"] / cur["total_assets"]
        if prev.get("revenue") and prev.get("total_assets") and prev["total_assets"] != 0:
            prev_at = prev["revenue"] / prev["total_assets"]
        if cur_at is not None and prev_at is not None and cur_at > prev_at:
            details.append({"criterion": "资产周转率同比提升", "passed": True, "score": 1,
                           "reason": f"{prev_at:.4f} → {cur_at:.4f}"})
        else:
            details.append({"criterion": "资产周转率同比提升", "passed": False, "score": 0, "reason": ""})

        score = sum(d["score"] for d in details)
        rating = FinancialAnalysisEngine._f_score_rating(score)
        return {"score": score, "details": details, "rating": rating,
                "max_score": 9, "explanation": FinancialAnalysisEngine._f_score_explanation(score)}

    @staticmethod
    def _f_score_rating(score: int) -> str:
        if score >= 8:
            return "优秀 (基本面强劲)"
        elif score >= 6:
            return "良好 (基本面较健康)"
        elif score >= 4:
            return "一般 (有改善空间)"
        elif score >= 2:
            return "较差 (基本面偏弱)"
        return "极差 (基本面堪忧)"

    @staticmethod
    def _f_score_explanation(score: int) -> str:
        if score >= 8:
            return "公司盈利能力、财务稳健性、运营效率均表现优异"
        elif score >= 6:
            return "公司在大部分维度表现良好，持续关注边际变化"
        elif score >= 4:
            return "公司基本面无明显优势，需观察改善趋势"
        elif score >= 2:
            return "公司在多个维度存在短板，投资需谨慎"
        return "公司基本面全面走弱，建议回避"

    # ── Altman Z-Score ──

    @staticmethod
    def altman_z_score(report: dict, market_cap: Optional[float] = None) -> dict:
        """Altman Z-Score (制造业): Z = 1.2*X1 + 1.4*X2 + 3.3*X3 + 0.6*X4 + 1.0*X5"""
        ta = report.get("total_assets")
        if not ta or ta == 0:
            return {"z_score": None, "rating": "数据不足", "components": {}}

        ca = report.get("current_assets")
        cl = report.get("current_liabilities")
        tl = report.get("total_liabilities")
        te = report.get("total_equity")
        rev = report.get("revenue")
        ni = report.get("net_profit")
        ebit = report.get("ebit") or ni  # 用净利润近似EBIT

        # X1 = 营运资本 / 总资产
        x1 = ((ca or 0) - (cl or 0)) / ta

        # X2 = 留存收益 / 总资产 (近似: 权益/总资产)
        x2 = (te or 0) / ta

        # X3 = EBIT / 总资产
        x3 = (ebit or 0) / ta

        # X4 = 市值 / 总负债
        x4 = (market_cap or (te or 1)) / (tl or 1) if tl and tl != 0 else 1.0

        # X5 = 营业收入 / 总资产
        x5 = (rev or 0) / ta

        z = round(1.2*x1 + 1.4*x2 + 3.3*x3 + 0.6*x4 + 1.0*x5, 3)

        return {
            "z_score": z,
            "rating": FinancialAnalysisEngine._z_score_rating(z),
            "components": {"X1_wc_ta": round(x1, 4), "X2_re_ta": round(x2, 4),
                          "X3_ebit_ta": round(x3, 4), "X4_mve_tl": round(x4, 4),
                          "X5_rev_ta": round(x5, 4)},
        }

    @staticmethod
    def _z_score_rating(z: float) -> str:
        if z > 2.99:
            return "安全区 (破产风险极低)"
        elif z > 1.81:
            return "灰色区 (需关注)"
        return "危险区 (破产风险较高)"

    # ── PE/PB Band ──

    @staticmethod
    def pe_pb_band(
        historical_pes: list[float],
        historical_pbs: list[float],
        current_pe: Optional[float] = None,
        current_pb: Optional[float] = None,
    ) -> dict:
        """PE/PB Band: 计算历史分位数 + 当前估值位置"""
        result = {"pe_band": {}, "pb_band": {}}

        for label, values, current in [
            ("pe_band", historical_pes, current_pe),
            ("pb_band", historical_pbs, current_pb),
        ]:
            if not values:
                result[label] = {"error": "无历史数据"}
                continue

            sorted_vals = sorted(v for v in values if v and v > 0)
            if len(sorted_vals) < 10:
                result[label] = {"error": "历史数据不足"}
                continue

            n = len(sorted_vals)
            band = {
                "min": sorted_vals[0],
                "p25": sorted_vals[n // 4],
                "median": sorted_vals[n // 2],
                "p75": sorted_vals[3 * n // 4],
                "max": sorted_vals[-1],
                "mean": round(sum(sorted_vals) / n, 2),
            }

            percentile = None
            if current is not None and current > 0:
                lower = sum(1 for v in sorted_vals if v <= current)
                percentile = round(lower / n * 100, 1)
                band["current"] = current
                band["percentile"] = percentile
                band["position"] = FinancialAnalysisEngine._band_position(percentile)

            result[label] = band

        return result

    @staticmethod
    def _band_position(percentile: float) -> str:
        if percentile <= 10:
            return "历史低位 (极度低估)"
        elif percentile <= 25:
            return "偏低区间 (估值有吸引力)"
        elif percentile <= 50:
            return "历史中位以下 (估值合理偏低)"
        elif percentile <= 75:
            return "历史中位以上 (估值合理偏高)"
        elif percentile <= 90:
            return "偏高区间 (估值偏贵)"
        return "历史高位 (估值泡沫风险)"

    # ── 综合财务健康度 ──

    @staticmethod
    def financial_health_summary(reports: list[dict]) -> dict:
        if not reports:
            return {"status": "no_data", "summary": "无财报数据"}

        latest = reports[0]
        dupont = FinancialAnalysisEngine.dupont_from_reports(reports)
        f_score = FinancialAnalysisEngine.piotroski_f_score(reports[:2]) if len(reports) >= 2 else {}
        z_score = FinancialAnalysisEngine.altman_z_score(latest)

        return {
            "latest_report_date": str(latest.get("report_date", "")),
            "latest_report_type": latest.get("report_type", ""),
            "revenue_yoy": latest.get("revenue_yoy"),
            "net_profit_yoy": latest.get("net_profit_yoy"),
            "roe": latest.get("roe"),
            "roa": latest.get("roa"),
            "gross_margin": latest.get("gross_margin"),
            "net_margin": latest.get("net_margin"),
            "eps": latest.get("eps"),
            "bvps": latest.get("bvps"),
            "debt_ratio": round(latest["total_liabilities"] / latest["total_assets"] * 100, 1)
                          if latest.get("total_assets") and latest.get("total_liabilities")
                          and latest["total_assets"] != 0 else None,
            "dupont": dupont,
            "f_score": f_score,
            "z_score": z_score,
            "data_quality": "real" if latest.get("source") else "estimated",
        }
