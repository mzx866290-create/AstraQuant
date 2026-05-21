from __future__ import annotations

import importlib
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


class MarketRedundancyCleanupTests(unittest.TestCase):
    def _load_module(self, db_path: Path):
        modules = [
            name
            for name in list(sys.modules)
            if name == "backend.shared.database"
            or name == "backend.services.analysis_service.engine.daily_snapshot_collector"
        ]
        for name in modules:
            sys.modules.pop(name, None)

        env = {
            "USE_SQLITE": "true",
            "DB_PATH": str(db_path),
            "APP_ENV": "development",
        }
        with patch.dict(os.environ, env, clear=False):
            database = importlib.import_module("backend.shared.database")
            database.init_db()
            collector = importlib.import_module("backend.services.analysis_service.engine.daily_snapshot_collector")
        return database, collector

    def test_cleanup_market_redundancy_applies_layered_retention(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database, collector = self._load_module(Path(tmpdir) / "cleanup.sqlite3")
            from backend.shared.models import (
                DailySnapshot,
                IndustryDailySnapshot,
                IndustryHealthScore,
                PipelineRunLog,
                RejectionLog,
            )

            old_date = (datetime.now() - timedelta(days=220)).strftime("%Y-%m-%d")
            recent_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
            db = database.SessionLocal()
            try:
                db.add_all([
                    DailySnapshot(trade_date=old_date, symbol="000001.SZ", market="SZ", close=1),
                    DailySnapshot(trade_date=recent_date, symbol="000002.SZ", market="SZ", close=1),
                    IndustryDailySnapshot(industry_code="I1", industry_name="Old", trade_date=old_date),
                    IndustryDailySnapshot(industry_code="I2", industry_name="New", trade_date=recent_date),
                    IndustryHealthScore(industry_code="I1", industry_name="Old", trade_date=old_date),
                    IndustryHealthScore(industry_code="I2", industry_name="New", trade_date=recent_date),
                    RejectionLog(symbol="000001.SZ", trade_date=old_date, reject_stage="scoring"),
                    RejectionLog(symbol="000002.SZ", trade_date=recent_date, reject_stage="scoring"),
                    PipelineRunLog(run_date=old_date, start_time=datetime.now(timezone.utc), status="success"),
                    PipelineRunLog(run_date=recent_date, start_time=datetime.now(timezone.utc), status="success"),
                ])
                db.commit()
            finally:
                db.close()

            try:
                result = collector.cleanup_market_redundancy(
                    daily_snapshot_days=180,
                    industry_snapshot_days=180,
                    industry_score_days=180,
                    rejection_log_days=120,
                    pipeline_log_days=180,
                )

                self.assertEqual(result["deleted"]["daily_snapshots"], 1)
                self.assertEqual(result["deleted"]["industry_daily_snapshots"], 1)
                self.assertEqual(result["deleted"]["industry_health_scores"], 1)
                self.assertEqual(result["deleted"]["rejection_logs"], 1)
                self.assertEqual(result["deleted"]["pipeline_run_logs"], 1)
                self.assertEqual(result["clickhouse"]["status"], "skipped_sqlite")
            finally:
                database.engine.dispose()


if __name__ == "__main__":
    unittest.main()
