from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.services.analysis_service.api.v1 import reviews


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(reviews.router)
    return TestClient(app)


class AnalysisReviewsApiTests(unittest.TestCase):
    def test_recent_reviews_endpoint_passes_validated_params(self) -> None:
        expected = {
            "status": "ok",
            "items": {"000001.SZ": []},
            "missing_symbols": [],
        }
        with patch.object(reviews, "build_recent_review_summaries", return_value=expected) as summaries:
            response = _client().get(
                "/recent",
                params={
                    "symbols": "000001.SZ,600000.SH",
                    "strategy": "auto",
                    "offsets": "T+1,T+5",
                    "limit_per_symbol": 1,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        summaries.assert_called_once_with(
            ["000001.SZ", "600000.SH"],
            strategy="auto",
            offsets=("T+1", "T+5"),
            limit_per_symbol=1,
        )

    def test_recent_reviews_endpoint_rejects_invalid_offsets(self) -> None:
        response = _client().get(
            "/recent",
            params={"symbols": "000001.SZ", "offsets": "T+2"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("offsets", response.json()["detail"])

    def test_recent_reviews_endpoint_rejects_limit_above_five(self) -> None:
        response = _client().get(
            "/recent",
            params={"symbols": "000001.SZ", "limit_per_symbol": 6},
        )

        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
