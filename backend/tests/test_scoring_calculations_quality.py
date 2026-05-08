from __future__ import annotations

import unittest

from backend.services.analysis_service.engine import scoring_calculations as calc


class FakeIndicatorEngine:
    def __init__(self, rsi_values: list[float | None]) -> None:
        self.rsi_values = rsi_values

    def rsi(self, kline_data: list[dict], period: int = 14) -> list[float | None]:
        return self.rsi_values


class FakeFinancialEngine:
    def __init__(self, f_score: int) -> None:
        self.f_score = f_score
        self.calls: list[list[dict]] = []

    def piotroski_f_score(self, reports: list[dict]) -> dict:
        self.calls.append(reports)
        return {"score": self.f_score}


class FakeSentimentEngine:
    def __init__(self, summary: dict) -> None:
        self.summary = summary
        self.calls: list[dict] = []

    def summarize_sentiment(self, news_list: list[dict], days: int = 7) -> dict:
        self.calls.append({"news_list": news_list, "days": days})
        return self.summary


def _kline_from_closes(closes: list[float], turnover_rates: list[float] | None = None) -> list[dict]:
    rows = []
    for idx, close in enumerate(closes):
        row = {"close": close}
        if turnover_rates is not None:
            row["turnover_rate"] = turnover_rates[idx]
        rows.append(row)
    return rows


def _kline_with_year_line_ratio(target_ratio: float, current: float = 100.0) -> list[dict]:
    previous = (current * 250 / target_ratio - current) / 249
    return _kline_from_closes([previous] * 249 + [current])


class ScoringCalculationsQualityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_indicator_engine = calc.indicator_engine
        self.original_financial_engine = calc.financial_engine
        self.original_sentiment_engine = calc.sentiment_engine

    def tearDown(self) -> None:
        calc.indicator_engine = self.original_indicator_engine
        calc.financial_engine = self.original_financial_engine
        calc.sentiment_engine = self.original_sentiment_engine

    def test_momentum_requires_sixty_points_and_clamps_extremes(self) -> None:
        insufficient = calc.compute_momentum(_kline_from_closes([10.0] * 59))
        self.assertEqual(insufficient["score"], 5.0)

        bullish = [1.0] * 60
        bullish[-1] = 100.0
        bearish = [100.0] * 60
        bearish[-1] = 1.0

        self.assertEqual(calc.compute_momentum(_kline_from_closes(bullish))["score"], 10.0)
        self.assertEqual(calc.compute_momentum(_kline_from_closes(bearish))["score"], 0.0)

    def test_technical_uses_latest_valid_rsi_boundary_bands(self) -> None:
        calc.indicator_engine = FakeIndicatorEngine([None, None])
        self.assertEqual(calc.compute_technical([])["score"], 5.0)

        cases = [
            (29.9, 8.0),
            (30.0, 6.0),
            (39.9, 6.0),
            (40.0, 7.0),
            (60.0, 7.0),
            (60.1, 6.0),
            (70.0, 6.0),
            (70.1, 4.0),
        ]
        for rsi_value, expected_score in cases:
            with self.subTest(rsi_value=rsi_value):
                calc.indicator_engine = FakeIndicatorEngine([None, rsi_value])
                self.assertEqual(calc.compute_technical([])["score"], expected_score)

    def test_value_estimates_from_year_line_boundaries_without_reports(self) -> None:
        short_history = calc.compute_value(_kline_from_closes([10.0] * 249), [])
        self.assertEqual(short_history["score"], 5.0)
        self.assertEqual(short_history["source"], "insufficient")

        cases = [
            (0.69, 8.0),
            (0.701, 6.5),
            (0.89, 6.5),
            (0.901, 5.5),
            (1.09, 5.5),
            (1.101, 4.0),
            (1.29, 4.0),
            (1.301, 2.5),
        ]
        for ratio, expected_score in cases:
            with self.subTest(year_line_ratio=ratio):
                result = calc.compute_value(_kline_with_year_line_ratio(ratio), [])
                self.assertEqual(result["score"], expected_score)
                self.assertEqual(result["source"], "kline_estimated")

    def test_value_financial_report_pe_pb_thresholds_and_missing_values(self) -> None:
        cases = [
            ({"pe_ttm": 9.99, "pb": 0.99}, 8.0),
            ({"pe_ttm": 10.0, "pb": 1.0}, 6.0),
            ({"pe_ttm": 20.0, "pb": 3.0}, 4.0),
            ({"pe_ttm": 40.0, "pb": 3.01}, 3.0),
            ({"pe_ttm": 0, "pb": 0}, 5.0),
        ]
        for report, expected_score in cases:
            with self.subTest(report=report):
                result = calc.compute_value([], [report])
                self.assertEqual(result["score"], expected_score)
                self.assertEqual(result["source"], "financial_reports")

    def test_quality_estimates_from_recent_trend_without_reports(self) -> None:
        short_history = calc.compute_quality(_kline_from_closes([10.0] * 59), [])
        self.assertEqual(short_history["score"], 5.0)
        self.assertEqual(short_history["source"], "insufficient")

        rising = [100.0] * 40 + [float(value) for value in range(101, 121)]
        falling = [100.0] * 40 + [float(value) for value in range(99, 79, -1)]

        strong = calc.compute_quality(_kline_from_closes(rising), [])
        weak = calc.compute_quality(_kline_from_closes(falling), [])

        self.assertEqual(strong["score"], 8.0)
        self.assertEqual(strong["source"], "kline_estimated")
        self.assertEqual(weak["score"], 4.0)
        self.assertEqual(weak["source"], "kline_estimated")

    def test_quality_financial_reports_apply_fundamental_and_fscore_bounds(self) -> None:
        strong_reports = [
            {"roe": 25.0, "gross_margin": 55.0, "net_profit_yoy": 40.0},
            {"roe": 15.0},
        ]
        calc.financial_engine = FakeFinancialEngine(9)
        strong = calc.compute_quality([], strong_reports)
        self.assertEqual(strong["score"], 10.0)
        self.assertEqual(strong["source"], "financial_reports")
        self.assertEqual(calc.financial_engine.calls, [strong_reports[:2]])

        weak_reports = [
            {"roe": 1.0, "gross_margin": 20.0, "net_profit_yoy": -5.0},
            {"roe": 2.0},
        ]
        calc.financial_engine = FakeFinancialEngine(2)
        weak = calc.compute_quality([], weak_reports)
        self.assertEqual(weak["score"], 2.5)
        self.assertEqual(weak["source"], "financial_reports")

    def test_sentiment_combines_news_flow_turnover_and_clamps_scores(self) -> None:
        positive_news = [{"title": "positive"}]
        upward_turnover = [1.0] * 5 + [1.3] * 5
        positive_flow = {
            "status": "ok",
            "data": [{"main_inflow": 100.0}] * 5,
            "warnings": [],
            "data_quality": {"confidence": 1.0},
        }
        calc.sentiment_engine = FakeSentimentEngine(
            {"total": 1, "positive_ratio": 100.0, "negative_ratio": 0.0}
        )
        high = calc.compute_sentiment(
            _kline_from_closes([10.0] * 10, upward_turnover),
            positive_news,
            positive_flow,
        )
        self.assertEqual(high["score"], 10.0)
        self.assertEqual(high["source"], "mixed")
        self.assertEqual(high["status"], "ok")
        self.assertEqual(high["data_quality"]["money_flow"]["confidence"], 1.0)

        downward_turnover = [1.0] * 5 + [0.7] * 5
        negative_flow = {
            "status": "ok",
            "data": [{"main_inflow": -100.0}] * 5,
            "warnings": [],
            "data_quality": {"confidence": 0.9},
        }
        calc.sentiment_engine = FakeSentimentEngine(
            {"total": 1, "positive_ratio": 0.0, "negative_ratio": 100.0}
        )
        low = calc.compute_sentiment(
            _kline_from_closes([10.0] * 10, downward_turnover),
            [{"title": "negative"}],
            negative_flow,
        )
        self.assertEqual(low["score"], 0.0)
        self.assertEqual(low["source"], "mixed")
        self.assertEqual(low["status"], "ok")

    def test_sentiment_marks_unavailable_and_partial_money_flow_states(self) -> None:
        unavailable_flow = {
            "status": "unavailable",
            "data": [],
            "warnings": ["money_flow_empty"],
            "data_quality": {"confidence": 0.05},
        }
        no_data = calc.compute_sentiment([], [], unavailable_flow)
        self.assertEqual(no_data["score"], 5.0)
        self.assertEqual(no_data["source"], "insufficient_without_money_flow")
        self.assertEqual(no_data["status"], "unavailable")
        self.assertEqual(no_data["warnings"], ["money_flow_empty"])

        calc.sentiment_engine = FakeSentimentEngine(
            {"total": 1, "positive_ratio": 50.0, "negative_ratio": 0.0}
        )
        partial = calc.compute_sentiment(
            [],
            [{"title": "some news"}],
            unavailable_flow,
        )
        self.assertEqual(partial["score"], 7.0)
        self.assertEqual(partial["source"], "partial_without_money_flow")
        self.assertEqual(partial["status"], "partial")
        self.assertEqual(partial["warnings"], ["money_flow_empty"])

    def test_to_rating_level_boundaries(self) -> None:
        cases = [
            (8.50, "A+"),
            (8.49, "A"),
            (7.00, "A"),
            (6.99, "B"),
            (5.50, "B"),
            (5.49, "C"),
            (4.00, "C"),
            (3.99, "D"),
        ]
        for score, expected_level in cases:
            with self.subTest(score=score):
                self.assertEqual(calc.to_rating(score)["level"], expected_level)


if __name__ == "__main__":
    unittest.main()
