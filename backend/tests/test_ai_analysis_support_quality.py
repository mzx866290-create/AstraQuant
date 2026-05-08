from __future__ import annotations

from datetime import date as real_date
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend.services.analysis_service.engine import ai_analysis_support as support


def _analysis_request(**overrides) -> SimpleNamespace:
    data = {
        "model_id": 1,
        "symbol": "000001",
        "framework": "fundamental",
        "question": "What changed?",
        "include_news": True,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _frozen_date(year: int, month: int, day: int):
    class FrozenDate:
        @classmethod
        def today(cls):
            return real_date(year, month, day)

    return FrozenDate


def _trust_boundary() -> dict:
    return {
        "facts": ["server fact one", "server fact two"],
        "rules": [{"label": "data rule", "level": "green", "message": "ok"}],
        "model": ["server model note"],
        "limits": ["server limit one", "server limit two"],
    }


class AnalysisCacheKeyTests(unittest.TestCase):
    def test_analysis_cache_key_changes_for_each_cache_input(self) -> None:
        request = _analysis_request()
        with patch.object(support, "date", _frozen_date(2026, 5, 7)):
            base = support.analysis_cache_key(
                42,
                request,
                "summary",
                "normal",
                "quick",
                "plain",
            )
            variants = {
                "user": support.analysis_cache_key(43, request, "summary", "normal", "quick", "plain"),
                "model": support.analysis_cache_key(
                    42, _analysis_request(model_id=2), "summary", "normal", "quick", "plain"
                ),
                "symbol": support.analysis_cache_key(
                    42, _analysis_request(symbol="000002"), "summary", "normal", "quick", "plain"
                ),
                "template": support.analysis_cache_key(42, request, "summary", "normal", "detailed", "plain"),
                "style": support.analysis_cache_key(42, request, "summary", "normal", "quick", "risk"),
                "mode": support.analysis_cache_key(42, request, "detailed", "normal", "quick", "plain"),
                "audience": support.analysis_cache_key(42, request, "summary", "beginner", "quick", "plain"),
                "framework": support.analysis_cache_key(
                    42, _analysis_request(framework="technical"), "summary", "normal", "quick", "plain"
                ),
                "question": support.analysis_cache_key(
                    42, _analysis_request(question="How risky?"), "summary", "normal", "quick", "plain"
                ),
                "include_news": support.analysis_cache_key(
                    42, _analysis_request(include_news=False), "summary", "normal", "quick", "plain"
                ),
            }

        with patch.object(support, "date", _frozen_date(2026, 5, 8)):
            variants["date"] = support.analysis_cache_key(42, request, "summary", "normal", "quick", "plain")

        for field, key in variants.items():
            with self.subTest(field=field):
                self.assertNotEqual(base, key)

    def test_batch_item_cache_key_changes_for_each_cache_input(self) -> None:
        with patch.object(support, "date", _frozen_date(2026, 5, 7)):
            base = support.batch_item_cache_key("000001", "summary", "normal", True)
            variants = {
                "symbol": support.batch_item_cache_key("000002", "summary", "normal", True),
                "mode": support.batch_item_cache_key("000001", "detailed", "normal", True),
                "audience": support.batch_item_cache_key("000001", "summary", "beginner", True),
                "include_news": support.batch_item_cache_key("000001", "summary", "normal", False),
            }

        with patch.object(support, "date", _frozen_date(2026, 5, 8)):
            variants["date"] = support.batch_item_cache_key("000001", "summary", "normal", True)

        for field, key in variants.items():
            with self.subTest(field=field):
                self.assertNotEqual(base, key)


class CachedAnalysisResponseTests(unittest.TestCase):
    def test_prepare_cached_analysis_response_returns_none_for_empty_cache(self) -> None:
        self.assertIsNone(support.prepare_cached_analysis_response(None))
        self.assertIsNone(support.prepare_cached_analysis_response({}))

    def test_prepare_cached_analysis_response_marks_cache_hit_and_clears_force_refresh(self) -> None:
        cached = {
            "analysis": "Cached report with enough neutral context for display.",
            "report_meta": {"force_refresh": True, "source": "cache"},
        }

        prepared = support.prepare_cached_analysis_response(cached)

        self.assertTrue(prepared["cache_hit"])
        self.assertFalse(prepared["report_meta"]["force_refresh"])
        self.assertEqual("cache", prepared["report_meta"]["source"])
        self.assertNotIn("cache_hit", cached)
        self.assertTrue(cached["report_meta"]["force_refresh"])

    def test_prepare_cached_analysis_response_can_skip_cache_hit_marking(self) -> None:
        cached = {
            "analysis": "Cached report with enough neutral context for display.",
            "report_meta": {"force_refresh": True},
        }

        prepared = support.prepare_cached_analysis_response(cached, mark_hit=False)

        self.assertNotIn("cache_hit", prepared)
        self.assertTrue(prepared["report_meta"]["force_refresh"])

    def test_prepare_cached_analysis_response_sanitizes_cached_direct_advice(self) -> None:
        cached = {
            "analysis": (
                "This cached analysis says buy after reviewing the setup and gives a "
                "target price for reference, but it is not personalized investment advice."
            ),
            "report_meta": {"force_refresh": True},
        }

        prepared = support.prepare_cached_analysis_response(cached)

        self.assertTrue(prepared["report_meta"]["sanitized"])
        self.assertNotIn("buy", prepared["analysis"].lower())
        self.assertNotIn("target price", prepared["analysis"].lower())


class CleanModelAnalysisTests(unittest.TestCase):
    def test_clean_model_analysis_rejects_too_short_content(self) -> None:
        with self.assertRaises(RuntimeError):
            support.clean_model_analysis("too short")

    def test_clean_model_analysis_sanitizes_direct_advice(self) -> None:
        cleaned, sanitized = support.clean_model_analysis(
            "This educational analysis says buy after reviewing risks. "
            "It also lists a target price, but it is not personalized advice."
        )

        self.assertTrue(sanitized)
        self.assertNotIn("buy", cleaned.lower())
        self.assertNotIn("target price", cleaned.lower())


class TrustBoundaryAttachmentTests(unittest.TestCase):
    def test_attach_trust_boundary_section_returns_empty_analysis_as_is(self) -> None:
        with patch.object(support.ReportGuard, "render_trust_boundary_section") as render:
            self.assertEqual("", support.attach_trust_boundary_section("", _trust_boundary()))

        render.assert_not_called()

    def test_attach_trust_boundary_section_replaces_existing_boundary(self) -> None:
        analysis = (
            "Main report body.\n\n"
            "## \u53ef\u4fe1\u8fb9\u754c\n"
            "model generated boundary\n\n"
            "## \u6570\u636e\u6765\u6e90\n"
            "source line"
        )

        guarded = support.attach_trust_boundary_section(analysis, _trust_boundary())

        self.assertNotIn("model generated boundary", guarded)
        self.assertEqual(1, guarded.count("server fact one"))
        self.assertLess(guarded.index("server fact one"), guarded.index("source line"))

    def test_attach_trust_boundary_section_inserts_before_sources(self) -> None:
        analysis = "Main report body.\n\n## \u6570\u636e\u6765\u6e90\nsource line"

        guarded = support.attach_trust_boundary_section(analysis, _trust_boundary())

        self.assertIn("server fact one", guarded)
        self.assertLess(guarded.index("server fact one"), guarded.index("## \u6570\u636e\u6765\u6e90"))

    def test_attach_trust_boundary_section_appends_when_sources_are_absent(self) -> None:
        analysis = "Main report body.\n\n## Existing Section\nexisting details"
        rendered = support.ReportGuard.render_trust_boundary_section(_trust_boundary())

        guarded = support.attach_trust_boundary_section(analysis, _trust_boundary())

        self.assertTrue(guarded.startswith(analysis))
        self.assertTrue(guarded.endswith(rendered))


class GuardedTrustAnalysisTests(unittest.TestCase):
    def test_build_guarded_trust_analysis_returns_boundary_and_writes_section(self) -> None:
        analysis = "Main report body.\n\n## \u6570\u636e\u6765\u6e90\nsource line"
        stock_data = {
            "readiness": {
                "data_grade": {
                    "grade": "A",
                    "label": "complete",
                    "analysis_scope": "full structured test scope",
                },
                "missing_context": ["peer comparison"],
            },
            "quote": {"source": "quote-unit"},
            "financial": {"source": "financial-unit"},
            "news": [{"title": "unit news"}],
        }
        risk_lights = {"data": {"label": "data light", "level": "green", "message": "ok"}}

        guarded, trust_boundary = support.build_guarded_trust_analysis(
            analysis,
            stock_data,
            risk_lights,
            status="success",
            fallback_reason=None,
            sanitized=True,
            trimmed=False,
        )

        self.assertEqual("success", trust_boundary["status"])
        self.assertTrue(trust_boundary["sanitized"])
        self.assertFalse(trust_boundary["trimmed"])
        self.assertIn(trust_boundary["facts"][0], guarded)
        self.assertIn("data light(green)", guarded)
        self.assertLess(guarded.index(trust_boundary["facts"][0]), guarded.index("source line"))


if __name__ == "__main__":
    unittest.main()
