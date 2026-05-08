import math
import sys
import types
import unittest
from datetime import datetime
from unittest.mock import Mock, patch

from backend.services.data_crawler.pipeline.financial_etl import (
    AnnouncementETL,
    FinancialReportETL,
)


class FakeSession:
    def __init__(self, rowcounts=None, *, fail_on_execute=False):
        self.rowcounts = list(rowcounts or [])
        self.fail_on_execute = fail_on_execute
        self.executed = []
        self.commits = 0
        self.rollbacks = 0

    def get_bind(self):
        return types.SimpleNamespace(dialect=types.SimpleNamespace(name="sqlite"))

    def execute(self, stmt):
        self.executed.append(stmt)
        if self.fail_on_execute:
            raise RuntimeError("write failed")
        rowcount = self.rowcounts.pop(0) if self.rowcounts else 0
        return types.SimpleNamespace(rowcount=rowcount)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def patched_save_imports():
    models = types.SimpleNamespace(
        CompanyAnnouncement=type("CompanyAnnouncement", (), {}),
        FinancialReport=type("FinancialReport", (), {}),
    )

    def insert_do_nothing(model, row, conflict_columns, dialect_name):
        return {
            "model": model.__name__,
            "row": dict(row),
            "conflict_columns": list(conflict_columns),
            "dialect_name": dialect_name,
        }

    upsert = types.SimpleNamespace(
        insert_do_nothing=insert_do_nothing,
        session_dialect_name=lambda session: session.get_bind().dialect.name,
    )
    return patch.dict(
        sys.modules,
        {
            "backend.shared.models": models,
            "backend.services.data_crawler.pipeline.upsert": upsert,
        },
    )


class AnnouncementETLTests(unittest.IsolatedAsyncioTestCase):
    def test_clean_filters_invalid_rows_and_normalizes_valid_announcements(self):
        etl = AnnouncementETL()
        raw_items = [
            {
                "title": "Annual report for fiscal 2025",
                "date": "2026-05-06",
                "summary": "A" * 2100,
                "url": "https://example.test/report.pdf",
            },
            {"title": "abc", "date": "2026-05-06"},
            {"title": "Valid title but no date", "date": ""},
        ]

        cleaned = etl.clean("600519.SH", raw_items, "unit")

        self.assertEqual(len(cleaned), 1)
        row = cleaned[0]
        self.assertEqual(row["stock_symbol"], "600519")
        self.assertEqual(row["title"], "Annual report for fiscal 2025")
        self.assertEqual(len(row["summary"]), 2000)
        self.assertEqual(row["content_url"], "https://example.test/report.pdf")
        self.assertEqual(row["announce_date"], datetime(2026, 5, 6))
        self.assertEqual(row["source"], "unit")

    async def test_save_returns_zero_without_touching_session_for_empty_cleaned_data(self):
        etl = AnnouncementETL()
        session = Mock()

        with patched_save_imports():
            saved = await etl.save(session, "600519", [{"title": "abc", "date": ""}], "unit")

        self.assertEqual(saved, 0)
        session.execute.assert_not_called()
        session.commit.assert_not_called()
        session.rollback.assert_not_called()

    async def test_save_counts_inserted_rows_and_uses_conflict_key(self):
        etl = AnnouncementETL()
        session = FakeSession(rowcounts=[1, 0])
        raw_items = [
            {"title": "First valid announcement", "date": "2026-05-06"},
            {"title": "Duplicate valid announcement", "date": "2026-05-07"},
        ]

        with patched_save_imports():
            saved = await etl.save(session, "600519.SH", raw_items, "unit")

        self.assertEqual(saved, 1)
        self.assertEqual(session.commits, 1)
        self.assertEqual(session.rollbacks, 0)
        self.assertEqual(len(session.executed), 2)
        self.assertEqual(
            session.executed[0]["conflict_columns"],
            ["stock_symbol", "title", "announce_date"],
        )
        self.assertEqual(session.executed[0]["dialect_name"], "sqlite")

    async def test_save_rolls_back_and_reraises_on_write_failure(self):
        etl = AnnouncementETL()
        session = FakeSession(fail_on_execute=True)

        with patched_save_imports():
            with self.assertRaisesRegex(RuntimeError, "write failed"):
                await etl.save(
                    session,
                    "600519",
                    [{"title": "Valid announcement title", "date": "2026-05-06"}],
                    "unit",
                )

        self.assertEqual(session.commits, 0)
        self.assertEqual(session.rollbacks, 1)


class FinancialReportETLTests(unittest.IsolatedAsyncioTestCase):
    def test_safe_float_rejects_empty_sentinel_and_non_finite_values(self):
        etl = FinancialReportETL()

        self.assertEqual(etl._safe_float("1,234.50"), 1234.5)
        self.assertEqual(etl._safe_float("12.5%"), 12.5)
        self.assertIsNone(etl._safe_float("--"))
        self.assertIsNone(etl._safe_float(False))
        self.assertIsNone(etl._safe_float(float("nan")))
        self.assertIsNone(etl._safe_float(math.inf))

    def test_merge_and_compute_aligns_reports_and_computes_ratios(self):
        etl = FinancialReportETL()
        balance_data = [
            {
                "report_date": "2026-12-31",
                "total_assets": "1,000",
                "total_liabilities": "400",
                "total_equity": "500",
                "current_assets": "300",
                "current_liabilities": "150",
            },
            {
                "report_date": "2026-09-30",
                "total_assets": "0",
                "total_equity": "0",
            },
        ]
        profit_data = [
            {
                "report_date": "2026-12-31",
                "revenue": "200",
                "net_profit": "50",
                "gross_margin": "25%",
                "net_margin": "10%",
                "eps": "1.23",
                "revenue_yoy": "8.5",
                "net_profit_yoy": "9.5",
            },
            {"report_date": "2026-09-30", "net_profit": "10"},
        ]
        cashflow_data = [
            {
                "report_date": "2026-12-31",
                "operating_cf": "70",
                "investing_cf": "-20",
                "financing_cf": "5",
            }
        ]

        rows = etl.merge_and_compute(
            "600519.SH",
            balance_data,
            profit_data,
            cashflow_data,
            source="unit",
        )

        self.assertEqual([row["report_date"] for row in rows], [datetime(2026, 12, 31), datetime(2026, 9, 30)])
        annual = rows[0]
        self.assertEqual(annual["stock_symbol"], "600519")
        self.assertEqual(annual["total_assets"], 1000.0)
        self.assertEqual(annual["revenue"], 200.0)
        self.assertEqual(annual["roe"], 10.0)
        self.assertEqual(annual["roa"], 5.0)
        self.assertEqual(annual["bvps"], 0.0)
        self.assertEqual(annual["operating_cf"], 70.0)
        self.assertEqual(annual["source"], "unit")
        self.assertIsNone(rows[1]["roe"])
        self.assertIsNone(rows[1]["roa"])

    def test_merge_and_compute_returns_empty_for_unusable_dates(self):
        etl = FinancialReportETL()

        rows = etl.merge_and_compute(
            "600519",
            balance_data=[{"report_date": "bad-date", "total_assets": "100"}],
            profit_data=[],
            cashflow_data=[{"report_date": "2026-12-31", "operating_cf": "70"}],
        )

        self.assertEqual(rows, [])

    async def test_save_counts_rows_and_preserves_idempotent_noop_rowcounts(self):
        etl = FinancialReportETL()
        session = FakeSession(rowcounts=[1, 0])
        balance_data = [
            {"report_date": "2026-12-31", "total_assets": "100", "total_equity": "50"},
            {"report_date": "2026-09-30", "total_assets": "80", "total_equity": "40"},
        ]

        with patched_save_imports():
            saved = await etl.save(session, "600519", balance_data, [], [], source="unit")

        self.assertEqual(saved, 1)
        self.assertEqual(session.commits, 1)
        self.assertEqual(session.rollbacks, 0)
        self.assertEqual(len(session.executed), 2)
        self.assertEqual(session.executed[0]["model"], "FinancialReport")
        self.assertEqual(session.executed[0]["conflict_columns"], ["stock_symbol", "report_date"])

    async def test_save_returns_zero_for_empty_merge_without_session_write(self):
        etl = FinancialReportETL()
        session = Mock()

        with patched_save_imports():
            saved = await etl.save(session, "600519", [], [], [], source="unit")

        self.assertEqual(saved, 0)
        session.execute.assert_not_called()
        session.commit.assert_not_called()
        session.rollback.assert_not_called()

    async def test_save_rolls_back_and_reraises_financial_write_failure(self):
        etl = FinancialReportETL()
        session = FakeSession(fail_on_execute=True)

        with patched_save_imports():
            with self.assertRaisesRegex(RuntimeError, "write failed"):
                await etl.save(
                    session,
                    "600519",
                    [{"report_date": "2026-12-31", "total_assets": "100"}],
                    [],
                    [],
                    source="unit",
                )

        self.assertEqual(session.commits, 0)
        self.assertEqual(session.rollbacks, 1)


if __name__ == "__main__":
    unittest.main()
