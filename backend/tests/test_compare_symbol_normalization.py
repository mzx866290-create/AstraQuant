from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch


class CompareSymbolNormalizationTests(unittest.TestCase):
    def test_normalize_symbol_list_accepts_prefixed_and_ss_symbols(self) -> None:
        from backend.services.analysis_service.api.v1 import compare

        self.assertEqual(
            compare._normalize_symbol_list("BJ830799, 430047.BJ, 600519.SS, 830799"),
            ["830799.BJ", "430047.BJ", "600519.SH"],
        )

    def test_compare_performance_uses_normalized_symbols(self) -> None:
        from backend.services.analysis_service.api.v1 import compare

        rows = [{"close": float(index)} for index in range(1, 18)]
        with patch.object(compare, "_fetch_kline", AsyncMock(return_value=rows)) as fetch_kline:
            result = asyncio.run(compare.compare_performance("BJ830799,600519.SS", periods="1d,5d"))

        self.assertEqual(result["symbols"], ["830799.BJ", "600519.SH"])
        self.assertIn("830799.BJ", result["data"])
        self.assertIn("600519.SH", result["data"])
        fetch_kline.assert_any_call("830799.BJ", 15)
        fetch_kline.assert_any_call("600519.SH", 15)


if __name__ == "__main__":
    unittest.main()
