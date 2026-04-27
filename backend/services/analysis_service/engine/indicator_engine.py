"""
技术指标计算引擎
支持: MA/EMA/MACD/BOLL/KDJ/RSI/VOL
输入: OHLC数组 → 输出: 指标值数组
"""
import math
from typing import Optional


class IndicatorEngine:
    """技术指标计算引擎"""

    @staticmethod
    def ma(data: list[dict], period: int = 5, field: str = "close") -> list[Optional[float]]:
        """
        简单移动平均线 MA
        :param data: OHLC数据列表 (需按时间正序)
        :param period: 周期 (5/10/20/60)
        :param field: 计算字段 (close/open/high/low)
        :return: 每个K线对应的MA值，不足周期返回None
        """
        result: list[Optional[float]] = []
        for i in range(len(data)):
            if i < period - 1:
                result.append(None)
            else:
                total = sum(float(data[j].get(field, 0)) for j in range(i - period + 1, i + 1))
                result.append(round(total / period, 4))
        return result

    @staticmethod
    def ema(data: list[dict], period: int = 12, field: str = "close") -> list[Optional[float]]:
        """
        指数移动平均线 EMA
        """
        result: list[Optional[float]] = []
        multiplier = 2 / (period + 1)
        prev_ema = None
        for i, item in enumerate(data):
            price = float(item.get(field, 0))
            if prev_ema is None:
                # 第一条用SMA
                if i < period - 1:
                    result.append(None)
                    continue
                total = sum(float(data[j].get(field, 0)) for j in range(i - period + 1, i + 1))
                prev_ema = total / period
            else:
                prev_ema = (price - prev_ema) * multiplier + prev_ema
            result.append(round(prev_ema, 4))
        return result

    @staticmethod
    def macd(data: list[dict], fast: int = 12, slow: int = 26, signal: int = 9,
             field: str = "close") -> dict:
        """
        MACD指标
        :return: {"dif": [...], "dea": [...], "macd_histogram": [...]}
        """
        engine = IndicatorEngine()
        ema_fast = engine.ema(data, fast, field)
        ema_slow = engine.ema(data, slow, field)

        dif: list[Optional[float]] = []
        for i in range(len(data)):
            if ema_fast[i] is not None and ema_slow[i] is not None:
                dif.append(round(ema_fast[i] - ema_slow[i], 4))
            else:
                dif.append(None)

        # DIF的EMA → DEA
        dea: list[Optional[float]] = []
        multiplier = 2 / (signal + 1)
        prev_dea = None
        for i, d in enumerate(dif):
            if d is None:
                dea.append(None)
                prev_dea = None
            elif prev_dea is None:
                # 取前signal个DIF的均值
                if i < signal - 1:
                    dea.append(None)
                    continue
                vals = [v for v in dif[i - signal + 1:i + 1] if v is not None]
                if len(vals) < signal:
                    dea.append(None)
                    continue
                prev_dea = sum(vals) / signal
                dea.append(round(prev_dea, 4))
            else:
                prev_dea = (d - prev_dea) * multiplier + prev_dea
                dea.append(round(prev_dea, 4))

        # MACD柱 = 2 * (DIF - DEA)
        histogram: list[Optional[float]] = []
        for i in range(len(data)):
            if dif[i] is not None and dea[i] is not None:
                histogram.append(round(2 * (dif[i] - dea[i]), 4))
            else:
                histogram.append(None)

        return {"dif": dif, "dea": dea, "histogram": histogram}

    @staticmethod
    def boll(data: list[dict], period: int = 20, multiplier: float = 2.0,
             field: str = "close") -> dict:
        """
        布林带 BOLL
        :return: {"upper": [...], "middle": [...], "lower": [...]}
        """
        engine = IndicatorEngine()
        middle = engine.ma(data, period, field)

        upper: list[Optional[float]] = []
        lower: list[Optional[float]] = []

        for i in range(len(data)):
            ma = middle[i]
            if ma is None:
                upper.append(None)
                lower.append(None)
                continue

            # 计算标准差
            vals = [float(data[j].get(field, 0)) for j in range(i - period + 1, i + 1)]
            if len(vals) < period:
                upper.append(None)
                lower.append(None)
                continue

            mean = sum(vals) / period
            variance = sum((v - mean) ** 2 for v in vals) / period
            std = math.sqrt(variance)

            upper.append(round(ma + multiplier * std, 4))
            lower.append(round(ma - multiplier * std, 4))

        return {"upper": upper, "middle": middle, "lower": lower}

    @staticmethod
    def kdj(data: list[dict], period: int = 9, k_smooth: int = 3, d_smooth: int = 3) -> dict:
        """
        KDJ指标 (随机指标)
        :return: {"k": [...], "d": [...], "j": [...]}
        """
        k_values: list[Optional[float]] = []
        d_values: list[Optional[float]] = []
        j_values: list[Optional[float]] = []

        prev_k = 50.0
        prev_d = 50.0

        for i in range(len(data)):
            if i < period - 1:
                k_values.append(None)
                d_values.append(None)
                j_values.append(None)
                continue

            high9 = max(float(data[j].get("high", 0)) for j in range(i - period + 1, i + 1))
            low9 = min(float(data[j].get("low", 0)) for j in range(i - period + 1, i + 1))
            close = float(data[i].get("close", 0))

            if high9 == low9:
                rsv = 50.0
            else:
                rsv = (close - low9) / (high9 - low9) * 100

            k = round(2 / 3 * prev_k + 1 / 3 * rsv, 4)
            d = round(2 / 3 * prev_d + 1 / 3 * k, 4)
            j = round(3 * k - 2 * d, 4)

            k_values.append(k)
            d_values.append(d)
            j_values.append(j)

            prev_k = k
            prev_d = d

        return {"k": k_values, "d": d_values, "j": j_values}

    @staticmethod
    def rsi(data: list[dict], period: int = 14, field: str = "close") -> list[Optional[float]]:
        """
        RSI (相对强弱指标)
        """
        result: list[Optional[float]] = []
        gains: list[float] = []
        losses: list[float] = []

        for i in range(len(data)):
            if i == 0:
                result.append(None)
                continue

            change = float(data[i].get(field, 0)) - float(data[i - 1].get(field, 0))
            gains.append(max(change, 0))
            losses.append(max(-change, 0))

            if i < period:
                result.append(None)
                continue

            avg_gain = sum(gains[i - period:i]) / period
            avg_loss = sum(losses[i - period:i]) / period

            if avg_loss == 0:
                rsi_val = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi_val = 100 - 100 / (1 + rs)

            result.append(round(rsi_val, 4))

        return result

    @staticmethod
    def volume_ma(data: list[dict], period: int = 5) -> list[Optional[float]]:
        """成交量均线"""
        return IndicatorEngine.ma(data, period, "volume")

    def compute_all(self, data: list[dict], indicators: list[str]) -> dict:
        """
        批量计算多个指标
        :param data: OHLC数据
        :param indicators: 指标名列表 ['ma5','ma20','macd','boll','kdj','rsi']
        :return: {指标名: 值列表}
        """
        result = {}
        for ind in indicators:
            ind_lower = ind.lower()
            if ind_lower == "macd":
                result[ind] = self.macd(data)
            elif ind_lower == "boll":
                result[ind] = self.boll(data)
            elif ind_lower == "kdj":
                result[ind] = self.kdj(data)
            elif ind_lower == "rsi":
                result[ind] = self.rsi(data)
            elif ind_lower.startswith("ma"):
                period = int(ind_lower.replace("ma", ""))
                result[ind] = self.ma(data, period)
            elif ind_lower.startswith("ema"):
                period = int(ind_lower.replace("ema", ""))
                result[ind] = self.ema(data, period)
            elif ind_lower.startswith("vol"):
                period = int(ind_lower.replace("vol", "")) if len(ind_lower) > 3 else 5
                result[ind] = self.volume_ma(data, period)
        return result
