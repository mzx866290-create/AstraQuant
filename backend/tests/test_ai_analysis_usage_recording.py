from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from backend.shared.models import AIUsageLog
from backend.services.analysis_service.engine.ai_analysis_service import _record_ai_usage


class AIUsageRecordingTests(unittest.TestCase):
    def test_success_usage_adds_log_increments_quota_and_commits(self) -> None:
        db = MagicMock()
        user = SimpleNamespace(id=42)
        model = SimpleNamespace(id=7)

        with patch(
            "backend.services.analysis_service.engine.ai_analysis_service.increment_quota"
        ) as increment_quota:
            log = _record_ai_usage(
                db,
                current_user=user,
                model=model,
                symbol="000001",
                prompt_tokens=11,
                completion_tokens=13,
                tokens_used=24,
                cost=0.12,
                status="success",
                error_message=None,
                response_time_ms=321,
            )

        self.assertIsInstance(log, AIUsageLog)
        self.assertIs(db.add.call_args.args[0], log)
        self.assertEqual(log.user_id, user.id)
        self.assertEqual(log.model_id, model.id)
        self.assertEqual(log.stock_symbol, "000001")
        self.assertEqual(log.prompt_tokens, 11)
        self.assertEqual(log.completion_tokens, 13)
        self.assertEqual(log.total_tokens, 24)
        self.assertEqual(log.cost, 0.12)
        self.assertEqual(log.status, "success")
        self.assertIsNone(log.error_message)
        self.assertEqual(log.response_time_ms, 321)
        increment_quota.assert_called_once_with(user.id)
        db.add.assert_called_once()
        db.commit.assert_called_once_with()

    def test_error_usage_adds_log_and_commits_without_incrementing_quota(self) -> None:
        db = MagicMock()
        user = SimpleNamespace(id=42)
        model = SimpleNamespace(id=7)

        with patch(
            "backend.services.analysis_service.engine.ai_analysis_service.increment_quota"
        ) as increment_quota:
            log = _record_ai_usage(
                db,
                current_user=user,
                model=model,
                symbol="000001",
                prompt_tokens=0,
                completion_tokens=0,
                tokens_used=0,
                cost=0.0,
                status="error",
                error_message="model unavailable",
                response_time_ms=0,
            )

        self.assertIsInstance(log, AIUsageLog)
        self.assertIs(db.add.call_args.args[0], log)
        self.assertEqual(log.user_id, user.id)
        self.assertEqual(log.model_id, model.id)
        self.assertEqual(log.stock_symbol, "000001")
        self.assertEqual(log.total_tokens, 0)
        self.assertEqual(log.cost, 0.0)
        self.assertEqual(log.status, "error")
        self.assertEqual(log.error_message, "model unavailable")
        self.assertEqual(log.response_time_ms, 0)
        increment_quota.assert_not_called()
        db.add.assert_called_once()
        db.commit.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
