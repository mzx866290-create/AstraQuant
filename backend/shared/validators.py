"""
数据质量校验 - 金融数据的完整性和逻辑一致性验证
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Tuple
import logging

logger = logging.getLogger(__name__)


class StockDataValidator:
    """股票数据多维度校验器"""

    @staticmethod
    def validate_ohlc(df: pd.DataFrame) -> Tuple[pd.DataFrame, dict]:
        """OHLC逻辑校验: High >= Low, High >= max(Open, Close), Low <= min(Open, Close)"""
        report = {"total": len(df), "issues": []}

        mask_hl = df["high"] >= df["low"]
        mask_ho = df["high"] >= df["open"]
        mask_hc = df["high"] >= df["close"]
        mask_lo = df["low"] <= df["open"]
        mask_lc = df["low"] <= df["close"]

        valid_mask = mask_hl & mask_ho & mask_hc & mask_lo & mask_lc
        invalid_count = (~valid_mask).sum()

        if invalid_count > 0:
            report["issues"].append(f"OHLC逻辑异常: {invalid_count}条")
            logger.warning(f"发现{invalid_count}条OHLC逻辑异常数据")

        return df[valid_mask].copy(), report

    @staticmethod
    def validate_continuity(df: pd.DataFrame, freq: str = "1d") -> Tuple[pd.DataFrame, dict]:
        """时间连续性校验: 检测缺失交易日"""
        report = {"missing_dates": []}

        if freq == "1d" and len(df) > 1:
            df = df.sort_values("date")
            date_range = pd.bdate_range(start=df["date"].min(), end=df["date"].max())
            existing = set(df["date"].dt.date)
            missing = [d.date() for d in date_range if d.date() not in existing]
            # 过滤掉已知的休市日（简化版，实际需接入交易日历）
            if missing:
                report["missing_dates"] = [str(d) for d in missing[:10]]  # 最多报告10个

        return df, report

    @staticmethod
    def validate_volume(df: pd.DataFrame) -> Tuple[pd.DataFrame, dict]:
        """成交量异常检测: 零成交量 + 极端值"""
        report = {"issues": []}

        zero_vol = (df["volume"] == 0).sum()
        if zero_vol > 0:
            report["issues"].append(f"零成交量: {zero_vol}条")

        if len(df) > 20:
            vol_mean = df["volume"].rolling(20).mean()
            vol_std = df["volume"].rolling(20).std()
            extreme_mask = df["volume"] > (vol_mean + 5 * vol_std)
            extreme_count = extreme_mask.sum()
            if extreme_count > 0:
                report["issues"].append(f"极端成交量(>5σ): {extreme_count}条")

        return df, report

    @staticmethod
    def validate_price_range(df: pd.DataFrame, pct_threshold: float = 0.2) -> Tuple[pd.DataFrame, dict]:
        """价格涨跌幅异常检测"""
        report = {"issues": []}

        if len(df) > 1:
            df = df.sort_values("date")
            df["prev_close"] = df["close"].shift(1)
            df["price_change_pct"] = abs((df["close"] - df["prev_close"]) / df["prev_close"])

            abnormal = (df["price_change_pct"] > pct_threshold).sum()
            if abnormal > 0:
                report["issues"].append(f"价格异常波动(>{pct_threshold*100}%): {abnormal}条")

            df = df.drop(columns=["prev_close", "price_change_pct"])

        return df, report

    def full_validate(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, dict]:
        """完整校验流水线"""
        full_report = {}
        df, r1 = self.validate_ohlc(df)
        full_report["ohlc"] = r1
        df, r2 = self.validate_continuity(df)
        full_report["continuity"] = r2
        df, r3 = self.validate_volume(df)
        full_report["volume"] = r3
        df, r4 = self.validate_price_range(df)
        full_report["price_range"] = r4
        full_report["clean_rows"] = len(df)
        return df, full_report


def validate_stock_symbol(symbol: str) -> bool:
    """验证股票代码格式"""
    return bool(symbol and len(symbol) <= 20)


def validate_email(email: str) -> bool:
    """简单的邮箱格式验证"""
    return bool(email and "@" in email and "." in email)
