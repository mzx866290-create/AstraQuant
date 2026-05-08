from __future__ import annotations

import unittest

from backend.services.analysis_service.engine.prompt_builder import PromptBuilder
from backend.services.analysis_service.engine.report_guard import ReportGuard


PROHIBITED_DIRECT_ADVICE_TERMS = ("买入", "卖出", "目标价", "满仓", "清仓")
NON_PERSONAL_BOUNDARY_MARKERS = (
    "Do not provide personalized buy/sell instructions",
    "non-personal decision framework",
    "End with:",
)


class PromptBuilderTrustBoundaryTests(unittest.TestCase):
    def test_system_prompt_sets_non_investment_advice_boundary(self) -> None:
        prompt = PromptBuilder.system_prompt(
            report_mode="detailed",
            audience="beginner",
            report_template="professional",
            prompt_style="risk_control",
        )

        for term in PROHIBITED_DIRECT_ADVICE_TERMS:
            self.assertNotIn(term, prompt)
        self.assertIn("Do not give personalized buy/sell instructions", prompt)
        self.assertIn("End with", prompt)

    def test_analysis_prompt_avoids_direct_advice_terms_and_requires_disclaimer(self) -> None:
        prompt = PromptBuilder.analysis_prompt(
            symbol="000001",
            stock_data={
                "name": "Ping An Bank",
                "price": 0,
                "quote": {"source": "unit-test"},
                "financial": {},
                "readiness": {"data_grade": {"grade": "D", "label": "missing", "analysis_scope": "data gaps only"}},
                "data_quality": {"quote": {"confidence": "low"}},
            },
            question="Can this be analyzed?",
            report_mode="summary",
            report_template="quick",
        )

        for term in PROHIBITED_DIRECT_ADVICE_TERMS:
            self.assertNotIn(term, prompt)
        self.assertIn("End with:", prompt)

    def test_follow_up_prompts_route_trade_questions_to_framework_not_commands(self) -> None:
        system_prompt = PromptBuilder.follow_up_system_prompt(audience="normal", prompt_style="plain")
        user_prompt = PromptBuilder.follow_up_prompt(
            symbol="000001",
            analysis="Prior report: risk is high and data is incomplete. This is for learning only.",
            question="Should I buy or sell now?",
        )
        combined = system_prompt + "\n" + user_prompt

        for term in PROHIBITED_DIRECT_ADVICE_TERMS:
            self.assertNotIn(term, combined)
        self.assertIn("non-personal decision framework", system_prompt)
        self.assertIn("Do not provide personalized buy/sell instructions", user_prompt)


class ReportGuardTrustBoundaryTests(unittest.TestCase):
    def test_ensure_content_preserves_non_investment_advice_boundary(self) -> None:
        guarded = ReportGuard.ensure_content(
            "This analysis uses watch points and risk reminders only. "
            "It is for learning and reference, not personalized investment advice."
        )

        for term in PROHIBITED_DIRECT_ADVICE_TERMS:
            self.assertNotIn(term, guarded)
        self.assertIn("not personalized investment advice", guarded)

    def test_enforce_length_does_not_add_direct_advice_terms(self) -> None:
        analysis = (
            "Risk framework only; not personalized investment advice.\n"
            + "\n".join(f"Line {idx}: observe risk, data quality, and invalidation conditions." for idx in range(120))
        )

        guarded, was_trimmed = ReportGuard.enforce_length(analysis, report_mode="summary", report_template="quick")

        self.assertTrue(was_trimmed)
        for term in PROHIBITED_DIRECT_ADVICE_TERMS:
            self.assertNotIn(term, guarded)

    def test_sanitize_advice_language_rewrites_direct_position_terms(self) -> None:
        sanitized, changed = ReportGuard.sanitize_advice_language("建议买入，目标价10元，满仓后再考虑清仓。")

        self.assertTrue(changed)
        for term in PROHIBITED_DIRECT_ADVICE_TERMS:
            self.assertNotIn(term, sanitized)

    def test_sanitize_advice_language_rewrites_common_chinese_position_commands(self) -> None:
        raw = "\u5efa\u8bae\u5efa\u4ed3\uff0c\u7ee7\u7eed\u6301\u6709\uff0c\u4ed3\u4f4d\u63d0\u9ad8\u523080%\uff0c\u76ee\u6807\u4f4d10\u5143\uff0c\u6b62\u635f\u4f4d8\u5143\u3002"
        sanitized, changed = ReportGuard.sanitize_advice_language(raw)

        self.assertTrue(changed)
        for term in ("\u5efa\u4ed3", "\u6301\u6709", "\u4ed3\u4f4d\u63d0\u9ad8", "\u76ee\u6807\u4f4d", "\u6b62\u635f\u4f4d"):
            self.assertNotIn(term, sanitized)

    def test_server_trust_boundary_replaces_model_generated_boundary(self) -> None:
        from backend.services.analysis_service.api.v1.ai_analysis import _attach_trust_boundary_section
        from backend.services.analysis_service.engine.ai_analysis_support import attach_trust_boundary_section

        analysis = "\u6b63\u6587\n\n## \u53ef\u4fe1\u8fb9\u754c\n\u6a21\u578b\u81ea\u5df1\u5199\u7684\u8fb9\u754c\n\n## \u6570\u636e\u6765\u6e90\nsource"
        boundary = {"facts": ["server facts"], "rules": [], "model": [], "limits": ["server limit"]}
        guarded = _attach_trust_boundary_section(analysis, boundary)

        self.assertIs(_attach_trust_boundary_section, attach_trust_boundary_section)
        self.assertNotIn("\u6a21\u578b\u81ea\u5df1\u5199\u7684\u8fb9\u754c", guarded)
        self.assertEqual(guarded.count("## \u53ef\u4fe1\u8fb9\u754c"), 1)
        self.assertIn("server facts", guarded)
        self.assertLess(guarded.index("server facts"), guarded.index("source"))

    def test_cached_analysis_is_sanitized_by_support_module(self) -> None:
        from backend.services.analysis_service.engine.ai_analysis_support import prepare_cached_analysis_response

        cached = {
            "analysis": "\u5efa\u8bae\u4e70\u5165\uff0c\u76ee\u6807\u4ef710\u5143\u3002\n\nAI\u5206\u6790\u4ec5\u4f9b\u53c2\u8003\uff0c\u4e0d\u6784\u6210\u6295\u8d44\u5efa\u8bae\u3002",
            "report_meta": {"force_refresh": True},
        }

        prepared = prepare_cached_analysis_response(cached)

        self.assertTrue(prepared["cache_hit"])
        self.assertFalse(prepared["report_meta"]["force_refresh"])
        self.assertTrue(prepared["report_meta"]["sanitized"])
        self.assertIn("\u4e0d\u6784\u6210\u6295\u8d44\u5efa\u8bae", prepared["analysis"])
        self.assertNotIn("\u4e70\u5165", prepared["analysis"])
        self.assertNotIn("\u76ee\u6807\u4ef7", prepared["analysis"])

    def test_build_trust_boundary_includes_non_investment_boundary(self) -> None:
        boundary = ReportGuard.build_trust_boundary(
            {
                "readiness": {
                    "data_grade": {"grade": "B", "label": "较完整", "analysis_scope": "可做结构化分析"},
                    "missing_context": ["northbound", "peer_comparison"],
                },
                "quote": {"source": "test"},
                "financial": {"source": "test"},
                "news": [{"title": "test"}],
            },
            {"data": {"label": "数据风险", "level": "yellow", "message": "存在少量缺失"}},
            status="success",
            fallback_reason=None,
            sanitized=True,
            trimmed=False,
        )

        self.assertIn("facts", boundary)
        self.assertIn("rules", boundary)
        self.assertIn("limits", boundary)
        rendered = ReportGuard.render_trust_boundary_section(boundary)
        self.assertIn("## 可信边界", rendered)
        self.assertIn("非投资建议边界", rendered)
        for term in PROHIBITED_DIRECT_ADVICE_TERMS:
            self.assertNotIn(term, rendered)


if __name__ == "__main__":
    unittest.main()
