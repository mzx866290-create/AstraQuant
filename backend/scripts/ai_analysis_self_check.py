from __future__ import annotations

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.services.analysis_service.api.v1.ai_analysis import _build_batch_brief, _build_batch_error_item
from backend.services.analysis_service.api.v1.ai_analysis import _cache_get, _cache_set
from backend.services.analysis_service.engine.data_quality import DataQualityBuilder, build_data_grade
from backend.services.analysis_service.engine.industry_event_impact import IndustryEventImpactEngine
from backend.services.analysis_service.engine.report_guard import ReportGuard
import asyncio


def main() -> None:
    stock_data = {
        "price": 0.0,
        "quote": {"source": "test", "price": 0.0},
        "quote_source": "test",
        "kline_source": "local-fallback",
        "kline_data": [],
        "financial": {},
        "announcements": [],
        "news": [],
        "news_sentiment": {},
        "industry_event_context": {},
    }
    quality = DataQualityBuilder.from_stock_data(stock_data)
    assert "latest_price_missing_or_zero" in quality["quote"]["warnings"]
    assert "kline_missing" in quality["kline"]["warnings"]
    assert "industry_events" in quality
    assert build_data_grade(stock_data)["grade"] == "D"

    c_grade = build_data_grade({
        "price": 10.0,
        "quote": {"pe_ttm": 12, "pb": 1.5, "open": 9.8, "high": 10.2, "low": 9.7, "volume": 1000},
        "kline_data": [{"close": 10}],
    })
    assert c_grade["grade"] in ("B", "C")

    long_report = "结论\n" + ("内容" * 1000) + "\n## 数据来源\n- test"
    trimmed, was_trimmed = ReportGuard.enforce_length(long_report, "summary")
    assert was_trimmed is True
    assert "## 数据来源" in trimmed
    assert len(trimmed) < len(long_report)

    brief = _build_batch_brief("920992.SH", {"name": "中科美菱", "price": 0.0, "financial": {}}, "beginner")
    assert "行情暂不可用" in brief
    assert "最新价 0.0" not in brief

    error_item = _build_batch_error_item("000000.SZ", "summary", "beginner", "boom")
    assert error_item["model_status"] == "error"
    assert error_item["risk_lights"]["data"]["level"] == "red"
    assert error_item["force_refresh"] is False

    industry_context = IndustryEventImpactEngine.analyze(
        "海康威视",
        "计算机设备",
        [
            {
                "title": "工信部推动人工智能和算力基础设施建设",
                "summary": "政策支持大模型、数据中心和智能终端发展",
                "source": "测试新闻",
                "publish_time": "2026-04-29",
                "related_sector": "计算机,通信,电子",
                "event_category": "政策",
            }
        ],
    )
    assert industry_context["available"] is True
    assert industry_context["themes"][0]["theme"] == "AI算力与数字经济"

    async def cache_check() -> None:
        await _cache_set("self-check-analysis", {
            "cache_hit": False,
            "report_meta": {"force_refresh": True, "trimmed": False},
        })
        cached = await _cache_get("self-check-analysis")
        assert cached["cache_hit"] is True
        assert cached["report_meta"]["force_refresh"] is False

        await _cache_set("self-check-batch", {"force_refresh": True}, category="ai_batch_summary")
        batch_cached = await _cache_get("self-check-batch", category="ai_batch_summary", mark_hit=False)
        assert "cache_hit" not in batch_cached

    asyncio.run(cache_check())

    print("ai_analysis_self_check passed")


if __name__ == "__main__":
    main()
