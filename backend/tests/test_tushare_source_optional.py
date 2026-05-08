import asyncio
import types
from unittest import TestCase
from unittest.mock import patch

from backend.services.data_crawler.sources import tushare_source
from backend.services.data_crawler.sources.tushare_source import TushareSource


class TushareSourceOptionalTests(TestCase):
    def test_missing_token_is_disabled_without_import_or_warning(self) -> None:
        with patch.object(tushare_source.importlib, "import_module") as import_module, \
             patch.object(tushare_source.logger, "warning") as warning:
            source = TushareSource(token="")

        self.assertEqual(source.availability_status, "disabled")
        self.assertIn("TUSHARE_TOKEN", source.unavailable_reason)
        import_module.assert_not_called()
        warning.assert_not_called()

        self.assertFalse(asyncio.run(source.health_check()))
        with self.assertRaisesRegex(RuntimeError, "已禁用.*TUSHARE_TOKEN"):
            asyncio.run(source.fetch_realtime_quote("600519"))

    def test_installed_package_missing_is_unavailable_without_warning(self) -> None:
        with patch.object(
            tushare_source.importlib,
            "import_module",
            side_effect=ImportError("no tushare"),
        ), patch.object(tushare_source.logger, "warning") as warning:
            source = TushareSource(token="unit-token")

        self.assertEqual(source.availability_status, "unavailable")
        self.assertIn("pip install tushare", source.unavailable_reason)
        warning.assert_not_called()

        self.assertFalse(asyncio.run(source.health_check()))
        with self.assertRaisesRegex(RuntimeError, "不可用.*未安装 tushare"):
            asyncio.run(source.fetch_daily_kline("600519"))

    def test_configured_and_installed_tushare_remains_available(self) -> None:
        calls = []

        class FakeApi:
            def daily(self, **kwargs):
                calls.append(("daily", kwargs))
                return types.SimpleNamespace(empty=False)

        fake_tushare = types.SimpleNamespace(
            set_token=lambda token: calls.append(("set_token", token)),
            pro_api=lambda: FakeApi(),
        )

        with patch.object(
            tushare_source.importlib,
            "import_module",
            return_value=fake_tushare,
        ):
            source = TushareSource(token="unit-token")
            healthy = asyncio.run(source.health_check())

        self.assertEqual(source.availability_status, "available")
        self.assertEqual(source.unavailable_reason, "")
        self.assertTrue(healthy)
        self.assertIn(("set_token", "unit-token"), calls)
        self.assertEqual(calls[-1][0], "daily")
