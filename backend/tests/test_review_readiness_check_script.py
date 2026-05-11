from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from backend.scripts import review_readiness_check


class ReviewReadinessCheckScriptTests(unittest.TestCase):
    def test_non_strict_returns_zero_for_local_missing_tables(self) -> None:
        stdout = io.StringIO()
        with patch(
            "sys.argv",
            ["review_readiness_check.py", "--date", "2026-05-11"],
        ), patch.object(
            review_readiness_check,
            "build_review_readiness",
            return_value={"status": "tables_missing", "summary": {}},
        ), redirect_stdout(stdout):
            exit_code = review_readiness_check.main()

        self.assertEqual(exit_code, 0)
        self.assertIn('"tables_missing"', stdout.getvalue())

    def test_strict_returns_two_for_missing_tables(self) -> None:
        with patch(
            "sys.argv",
            ["review_readiness_check.py", "--date", "2026-05-11", "--strict"],
        ), patch.object(
            review_readiness_check,
            "build_review_readiness",
            return_value={"status": "tables_missing", "summary": {}},
        ), redirect_stdout(io.StringIO()):
            exit_code = review_readiness_check.main()

        self.assertEqual(exit_code, 2)

    def test_require_reviewed_returns_three_when_no_reviews_exist(self) -> None:
        with patch(
            "sys.argv",
            ["review_readiness_check.py", "--date", "2026-05-11", "--require-reviewed"],
        ), patch.object(
            review_readiness_check,
            "build_review_readiness",
            return_value={"status": "no_pending_reviews", "summary": {"observations": 4, "reviews": 0}},
        ), redirect_stdout(io.StringIO()):
            exit_code = review_readiness_check.main()

        self.assertEqual(exit_code, 3)

    def test_require_reviewed_passes_when_reviews_exist(self) -> None:
        with patch(
            "sys.argv",
            ["review_readiness_check.py", "--date", "2026-05-11", "--require-reviewed"],
        ), patch.object(
            review_readiness_check,
            "build_review_readiness",
            return_value={"status": "reviewed", "summary": {"observations": 4, "reviews": 1}},
        ), redirect_stdout(io.StringIO()):
            exit_code = review_readiness_check.main()

        self.assertEqual(exit_code, 0)

    def test_require_no_pending_returns_four_when_reviews_are_pending(self) -> None:
        with patch(
            "sys.argv",
            ["review_readiness_check.py", "--date", "2026-05-11", "--require-no-pending"],
        ), patch.object(
            review_readiness_check,
            "build_review_readiness",
            return_value={"status": "pending_reviews", "summary": {"observations": 4, "reviews": 1, "pending_reviews": 2}},
        ), redirect_stdout(io.StringIO()):
            exit_code = review_readiness_check.main()

        self.assertEqual(exit_code, 4)

    def test_require_no_pending_passes_when_pending_reviews_are_clear(self) -> None:
        with patch(
            "sys.argv",
            ["review_readiness_check.py", "--date", "2026-05-11", "--require-no-pending"],
        ), patch.object(
            review_readiness_check,
            "build_review_readiness",
            return_value={"status": "reviewed", "summary": {"observations": 4, "reviews": 1, "pending_reviews": 0}},
        ), redirect_stdout(io.StringIO()):
            exit_code = review_readiness_check.main()

        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
