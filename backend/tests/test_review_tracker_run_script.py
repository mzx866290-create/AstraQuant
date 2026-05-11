from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import AsyncMock, patch

from backend.scripts import review_tracker_run


def _decode_json_documents(output: str) -> list[dict]:
    decoder = json.JSONDecoder()
    documents = []
    index = 0
    while index < len(output):
        while index < len(output) and output[index].isspace():
            index += 1
        if index >= len(output):
            break
        document, index = decoder.raw_decode(output, index)
        documents.append(document)
    return documents


class ReviewTrackerRunScriptTests(unittest.TestCase):
    def test_include_readiness_prints_run_report_and_readiness(self) -> None:
        stdout = io.StringIO()
        with patch(
            "sys.argv",
            [
                "review_tracker_run.py",
                "--date",
                "2026-05-11",
                "--offsets",
                "T+1",
                "--include-readiness",
            ],
        ), patch.object(
            review_tracker_run,
            "run_pending_reviews",
            AsyncMock(return_value={"status": "ok", "created": 1}),
        ) as run_reviews, patch.object(
            review_tracker_run,
            "build_review_report",
            return_value={"status": "ok", "summary": {"reviews": 1}},
        ), patch.object(
            review_tracker_run,
            "build_review_readiness",
            return_value={"status": "reviewed", "summary": {"observations": 1}},
        ) as readiness, redirect_stdout(stdout):
            exit_code = review_tracker_run.asyncio.run(review_tracker_run._main())

        self.assertEqual(exit_code, 0)
        payloads = _decode_json_documents(stdout.getvalue())
        self.assertEqual(payloads[0]["run_pending_reviews"]["status"], "ok")
        self.assertEqual(payloads[1]["review_report"]["summary"]["reviews"], 1)
        self.assertEqual(payloads[2]["review_readiness"]["status"], "reviewed")
        self.assertEqual(run_reviews.call_args.kwargs["offsets"], ("T+1",))
        self.assertEqual(readiness.call_args.kwargs["offsets"], ("T+1",))

    def test_report_only_skips_run_pending_reviews(self) -> None:
        stdout = io.StringIO()
        with patch(
            "sys.argv",
            ["review_tracker_run.py", "--date", "2026-05-11", "--report-only"],
        ), patch.object(
            review_tracker_run,
            "run_pending_reviews",
            AsyncMock(return_value={"status": "ok"}),
        ) as run_reviews, patch.object(
            review_tracker_run,
            "build_review_report",
            return_value={"status": "ok", "summary": {"reviews": 0}},
        ), redirect_stdout(stdout):
            exit_code = review_tracker_run.asyncio.run(review_tracker_run._main())

        self.assertEqual(exit_code, 0)
        self.assertEqual(run_reviews.await_count, 0)
        self.assertIn('"review_report"', stdout.getvalue())
        self.assertNotIn('"run_pending_reviews"', stdout.getvalue())

    def test_strict_readiness_returns_non_zero_for_not_ready_state(self) -> None:
        stdout = io.StringIO()
        with patch(
            "sys.argv",
            ["review_tracker_run.py", "--date", "2026-05-11", "--strict-readiness"],
        ), patch.object(
            review_tracker_run,
            "run_pending_reviews",
            AsyncMock(return_value={"status": "tables_missing", "created": 0}),
        ), patch.object(
            review_tracker_run,
            "build_review_report",
            return_value={"status": "tables_missing", "summary": {}},
        ), patch.object(
            review_tracker_run,
            "build_review_readiness",
            return_value={"status": "tables_missing", "summary": {}},
        ), redirect_stdout(stdout):
            exit_code = review_tracker_run.asyncio.run(review_tracker_run._main())

        self.assertEqual(exit_code, 2)
        self.assertIn('"review_readiness"', stdout.getvalue())

    def test_require_reviewed_returns_non_zero_when_no_reviews_exist(self) -> None:
        stdout = io.StringIO()
        with patch(
            "sys.argv",
            ["review_tracker_run.py", "--date", "2026-05-11", "--report-only", "--require-reviewed"],
        ), patch.object(
            review_tracker_run,
            "run_pending_reviews",
            AsyncMock(return_value={"status": "ok"}),
        ), patch.object(
            review_tracker_run,
            "build_review_report",
            return_value={"status": "ok", "summary": {"reviews": 0}},
        ), patch.object(
            review_tracker_run,
            "build_review_readiness",
            return_value={"status": "no_pending_reviews", "summary": {"observations": 3, "reviews": 0}},
        ), redirect_stdout(stdout):
            exit_code = review_tracker_run.asyncio.run(review_tracker_run._main())

        self.assertEqual(exit_code, 3)
        self.assertIn('"review_readiness"', stdout.getvalue())

    def test_require_reviewed_passes_when_reviews_exist(self) -> None:
        stdout = io.StringIO()
        with patch(
            "sys.argv",
            ["review_tracker_run.py", "--date", "2026-05-11", "--report-only", "--require-reviewed"],
        ), patch.object(
            review_tracker_run,
            "build_review_report",
            return_value={"status": "ok", "summary": {"reviews": 2}},
        ), patch.object(
            review_tracker_run,
            "build_review_readiness",
            return_value={"status": "reviewed", "summary": {"observations": 3, "reviews": 2}},
        ), redirect_stdout(stdout):
            exit_code = review_tracker_run.asyncio.run(review_tracker_run._main())

        self.assertEqual(exit_code, 0)
        self.assertIn('"reviews": 2', stdout.getvalue())

    def test_require_no_pending_returns_non_zero_when_pending_reviews_remain(self) -> None:
        stdout = io.StringIO()
        with patch(
            "sys.argv",
            ["review_tracker_run.py", "--date", "2026-05-11", "--report-only", "--require-no-pending"],
        ), patch.object(
            review_tracker_run,
            "build_review_report",
            return_value={"status": "ok", "summary": {"reviews": 2}},
        ), patch.object(
            review_tracker_run,
            "build_review_readiness",
            return_value={"status": "pending_reviews", "summary": {"observations": 4, "reviews": 2, "pending_reviews": 1}},
        ), redirect_stdout(stdout):
            exit_code = review_tracker_run.asyncio.run(review_tracker_run._main())

        self.assertEqual(exit_code, 4)
        self.assertIn('"pending_reviews": 1', stdout.getvalue())

    def test_require_no_pending_passes_when_pending_reviews_are_clear(self) -> None:
        stdout = io.StringIO()
        with patch(
            "sys.argv",
            ["review_tracker_run.py", "--date", "2026-05-11", "--report-only", "--require-no-pending"],
        ), patch.object(
            review_tracker_run,
            "build_review_report",
            return_value={"status": "ok", "summary": {"reviews": 2}},
        ), patch.object(
            review_tracker_run,
            "build_review_readiness",
            return_value={"status": "reviewed", "summary": {"observations": 4, "reviews": 2, "pending_reviews": 0}},
        ), redirect_stdout(stdout):
            exit_code = review_tracker_run.asyncio.run(review_tracker_run._main())

        self.assertEqual(exit_code, 0)
        self.assertIn('"pending_reviews": 0', stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
