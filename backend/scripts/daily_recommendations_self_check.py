from __future__ import annotations

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.services.analysis_service.engine.recommendation_engine import _build_score_breakdown, _score_daily_candidate


def main() -> None:
    stock_data = {
        "price": 12.5,
        "quote": {
            "pe_ttm": 18,
            "pb": 1.8,
            "total_mv": 12_000_000_000,
        },
        "financial": {},
        "kline_data": [
            {"close": 10 + i * 0.05, "volume": 1_000_000 + i * 10_000}
            for i in range(25)
        ],
        "news_sentiment": {},
        "industry_event_context": {"available": False, "themes": []},
        "readiness": {"data_grade": {"grade": "B"}},
    }
    risk_lights = {
        "data": {"level": "green", "message": "ok"},
        "valuation": {"level": "green", "message": "ok"},
        "financial": {"level": "yellow", "message": "financial missing"},
        "news": {"level": "yellow", "message": "news missing"},
        "industry_events": {"level": "yellow", "message": "industry missing"},
        "technical": {"level": "green", "message": "ok"},
    }
    score, reasons, risks = _score_daily_candidate(stock_data, risk_lights, "retail_small")
    breakdown = _build_score_breakdown(stock_data, risk_lights, "retail_small")
    assert score >= 60
    assert any("单手成本" in item for item in reasons)
    assert any("市值" in item for item in reasons)
    assert any(item["key"] == "retail_affordability" and item["delta"] > 0 for item in breakdown)
    assert any(item["key"] == "market_cap" and item["delta"] > 0 for item in breakdown)

    high_price_data = dict(stock_data)
    high_price_data["price"] = 180
    high_score, _, high_risks = _score_daily_candidate(high_price_data, risk_lights, "retail_small")
    assert high_score < score
    assert any("单手成本偏高" in item for item in high_risks)

    print("daily_recommendations_self_check passed")


if __name__ == "__main__":
    main()
