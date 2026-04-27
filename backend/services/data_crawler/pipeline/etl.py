"""
ETL管道 - 数据清洗 + 标准化 + 写入ClickHouse
"""
import logging
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class KLineETL:
    """K线数据ETL管道"""

    async def save_daily_kline(
        self,
        symbol: str,
        data: list[dict],
        source: str,
        adjust_flag: int = 1,
    ):
        """
        清洗并保存日K线数据到ClickHouse

        - 校验OHLC逻辑
        - 补全缺失字段
        - 批量写入
        """
        if not data:
            logger.warning(f"[{symbol}] 无数据可写入")
            return

        cleaned = []
        for item in data:
            row = self._clean_row(symbol, item, source, adjust_flag)
            if row:
                cleaned.append(row)

        if cleaned:
            await self._batch_write(cleaned)
            logger.info(f"[{symbol}] 写入 {len(cleaned)} 条K线数据")
        else:
            logger.warning(f"[{symbol}] 清洗后无有效数据")

    def _clean_row(self, symbol: str, item: dict, source: str, adjust_flag: int) -> Optional[dict]:
        """清洗单条K线数据"""
        try:
            open_px = float(item.get("open", 0))
            high = float(item.get("high", 0))
            low = float(item.get("low", 0))
            close = float(item.get("close", 0))
            volume = int(float(item.get("volume", 0)))
            turnover = float(item.get("turnover", 0))

            # OHLC逻辑校验
            if high < low or high < max(open_px, close) or low > min(open_px, close):
                logger.debug(f"[{symbol}] OHLC异常跳过: {item.get('date')}")
                return None

            date_val = item.get("date", "")
            if not date_val:
                return None

            return {
                "symbol": symbol[:6],
                "name": item.get("name", ""),
                "date": date_val[:10],
                "open": open_px,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "turnover": turnover,
                "change_pct": float(item.get("change_pct", 0)),
                "change": float(item.get("change", 0)),
                "amplitude": float(item.get("amplitude", 0)),
                "turnover_rate": float(item.get("turnover_rate", 0)),
                "up_limit": float(item.get("up_limit", 0)),
                "down_limit": float(item.get("down_limit", 0)),
                "pe_ttm": float(item.get("pe_ttm", 0)),
                "total_mv": float(item.get("total_mv", 0)),
                "circ_mv": float(item.get("circ_mv", 0)),
                "adjust_flag": adjust_flag,
                "source": source,
            }
        except (ValueError, TypeError) as e:
            logger.debug(f"[{symbol}] 数据解析失败: {e}")
            return None

    async def _batch_write(self, rows: list[dict]):
        """批量写入ClickHouse"""
        # TODO: 实现ClickHouse批量写入
        # 使用 clickhouse-driver 的 execute 批量插入
        logger.debug(f"批量写入 {len(rows)} 条 (待实现ClickHouse连接)")
        pass
