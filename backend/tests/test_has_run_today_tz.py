"""Regression tests for has_run_today timezone handling.

The DB stores PipelineRunLog.start_time as a naive datetime. The stuck-run
auto-recovery used datetime.now(timezone.utc) (aware) minus start_time (naive),
which raised TypeError and crashed the whole scheduler loop, so the pipeline
never ran again. These tests pin the naive/aware coercion in place.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from backend.services.analysis_service.engine import daily_pool_pipeline as pipeline


class _FakeQuery:
    def __init__(self, record):
        self._record = record

    def filter_by(self, **_kwargs):
        return self

    def first(self):
        return self._record


class _FakeSession:
    def __init__(self, record):
        self._record = record
        self.committed = False

    def query(self, *_args, **_kwargs):
        return _FakeQuery(self._record)

    def commit(self):
        self.committed = True

    def close(self):
        pass


class HasRunTodayTimezoneTests(unittest.TestCase):
    def test_naive_start_time_does_not_raise_and_auto_recovers(self) -> None:
        # Stuck in running for > 5 minutes, naive start_time (as stored in DB).
        naive_start = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=10)
        record = SimpleNamespace(
            status="running",
            start_time=naive_start,
            end_time=None,
            error_message=None,
        )
        session = _FakeSession(record)

        with patch.object(pipeline, "SessionLocal", return_value=session):
            result = pipeline.has_run_today("2026-05-14")

        # Did not raise; stuck record auto-recovered to failed.
        self.assertFalse(result)
        self.assertEqual(record.status, "failed")
        self.assertIn("auto-recovered", record.error_message or "")
        self.assertTrue(session.committed)

    def test_recent_running_record_is_left_alone(self) -> None:
        naive_start = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)
        record = SimpleNamespace(
            status="running",
            start_time=naive_start,
            end_time=None,
            error_message=None,
        )
        session = _FakeSession(record)

        with patch.object(pipeline, "SessionLocal", return_value=session):
            result = pipeline.has_run_today("2026-05-14")

        self.assertFalse(result)
        self.assertEqual(record.status, "running")
        self.assertFalse(session.committed)

    def test_success_record_reports_already_run(self) -> None:
        record = SimpleNamespace(
            status="success",
            start_time=None,
            end_time=None,
            error_message=None,
        )
        session = _FakeSession(record)

        with patch.object(pipeline, "SessionLocal", return_value=session):
            result = pipeline.has_run_today("2026-05-14")

        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
