from __future__ import annotations

import unittest

from backend.services.analysis_service.engine.prompt_builder import (
    PromptBuilder,
    fmt_billion,
    fmt_pct,
    fmt_price,
)


class PromptBuilderQualityEdgeTests(unittest.TestCase):
    def test_fmt_billion_handles_none_invalid_units_and_decimals(self) -> None:
        cases = [
            (None, "N/A"),
            ("not-a-number", "N/A"),
            (150_000_000, "1.50亿元"),
            (-250_000_000, "-2.50亿元"),
            (12_345, "1.23万元"),
            (123.456, "123.46"),
        ]

        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(fmt_billion(raw), expected)

    def test_fmt_pct_handles_none_invalid_and_valid_values(self) -> None:
        cases = [
            (None, "N/A"),
            ("bad", "N/A"),
            (12.345, "12.35%"),
            ("3.1", "3.10%"),
        ]

        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(fmt_pct(raw), expected)

    def test_fmt_price_marks_missing_invalid_and_zero_as_unavailable(self) -> None:
        cases = [
            (None, "行情不可用"),
            ("bad", "行情不可用"),
            (0, "行情不可用"),
            ("0.00", "行情不可用"),
            (12.345, "12.35"),
        ]

        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(fmt_price(raw), expected)

    def test_normalizers_accept_known_values_and_fall_back_for_unknown_values(self) -> None:
        self.assertEqual(PromptBuilder.normalize_report_mode("summary"), "summary")
        self.assertEqual(PromptBuilder.normalize_report_mode("detailed"), "detailed")
        self.assertEqual(PromptBuilder.normalize_report_mode(None), "summary")
        self.assertEqual(PromptBuilder.normalize_report_mode("full"), "summary")

        self.assertEqual(PromptBuilder.normalize_report_template("quick"), "quick")
        self.assertEqual(PromptBuilder.normalize_report_template("professional"), "professional")
        self.assertEqual(PromptBuilder.normalize_report_template("teaching"), "teaching")
        self.assertEqual(PromptBuilder.normalize_report_template(None), "quick")
        self.assertEqual(PromptBuilder.normalize_report_template("long"), "quick")

        self.assertEqual(PromptBuilder.normalize_audience("normal"), "normal")
        self.assertEqual(PromptBuilder.normalize_audience("beginner"), "beginner")
        self.assertEqual(PromptBuilder.normalize_audience(None), "normal")
        self.assertEqual(PromptBuilder.normalize_audience("expert"), "normal")

        for style in ("plain", "beginner", "professional", "risk_control"):
            with self.subTest(style=style):
                self.assertEqual(PromptBuilder.normalize_prompt_style(style), style)

        self.assertEqual(PromptBuilder.normalize_prompt_style(None), "default")
        self.assertEqual(PromptBuilder.normalize_prompt_style(""), "default")
        self.assertEqual(PromptBuilder.normalize_prompt_style("default"), "default")
        self.assertEqual(PromptBuilder.normalize_prompt_style("unknown", audience="normal"), "default")
        self.assertEqual(PromptBuilder.normalize_prompt_style("unknown", audience="beginner"), "beginner")

    def test_model_and_follow_up_configs_are_fixed_by_mode_and_template(self) -> None:
        self.assertEqual(
            PromptBuilder.model_config("summary", "professional"),
            {"temperature": 0.25, "timeout": 240, "max_retries": 0, "max_tokens": 3600},
        )
        self.assertEqual(
            PromptBuilder.model_config("summary", "teaching"),
            {"temperature": 0.28, "timeout": 240, "max_retries": 0, "max_tokens": 3800},
        )
        self.assertEqual(
            PromptBuilder.model_config("detailed", "quick"),
            {"temperature": 0.3, "timeout": 150, "max_retries": 0, "max_tokens": 1800},
        )
        self.assertEqual(
            PromptBuilder.model_config("summary", "quick"),
            {"temperature": 0.25, "timeout": 90, "max_retries": 0, "max_tokens": 950},
        )
        self.assertEqual(
            PromptBuilder.follow_up_config(),
            {"temperature": 0.25, "timeout": 90, "max_retries": 0, "max_tokens": 1000},
        )

    def test_system_prompt_uses_each_template_section_rule(self) -> None:
        quick = PromptBuilder.system_prompt(report_template="quick")
        professional = PromptBuilder.system_prompt(report_template="professional")
        teaching = PromptBuilder.system_prompt(report_template="teaching")

        self.assertIn("Quick template: 600-1000 Chinese characters", quick)
        self.assertIn("1. 先说结论", quick)
        self.assertIn("5. 数据缺口与免责声明", quick)

        self.assertIn("Professional template: 3000-5200 Chinese characters", professional)
        self.assertIn("1. 公司概况与业务模式", professional)
        self.assertIn("8. 投资决策框架（非投资建议）", professional)

        self.assertIn("Teaching template: 3000-5600 Chinese characters", teaching)
        self.assertIn("1. 卷首语：分析师的投研教学", teaching)
        self.assertIn("8. 纪律触发器与免责声明", teaching)

    def test_system_prompt_adds_style_rules_and_truncates_custom_prompt(self) -> None:
        style_expectations = {
            "plain": "Prompt style is plain-language",
            "beginner": "assume the reader has little finance background",
            "professional": "concise sell-side research language",
            "risk_control": "prioritize downside risks",
        }

        for style, phrase in style_expectations.items():
            with self.subTest(style=style):
                prompt = PromptBuilder.system_prompt(prompt_style=style)
                self.assertIn(phrase, prompt)

        custom_prompt = ("A" * 1200) + "SHOULD_NOT_APPEAR"
        prompt = PromptBuilder.system_prompt(custom_prompt=custom_prompt)
        extra = prompt.split("Additional admin instruction:\n", 1)[1]

        self.assertEqual(extra, "A" * 1200)
        self.assertNotIn("SHOULD_NOT_APPEAR", prompt)

    def test_follow_up_system_prompt_applies_styles_and_keeps_disclaimer(self) -> None:
        disclaimer = "以上解读仅供学习和参考，不构成投资建议。"
        style_expectations = {
            "plain": "Prompt style is plain-language",
            "beginner": "Prompt style is beginner teaching",
            "professional": "Prompt style is professional research",
            "risk_control": "Prompt style is risk-control first",
        }

        default_prompt = PromptBuilder.follow_up_system_prompt()
        self.assertIn(disclaimer, default_prompt)
        self.assertNotIn("Prompt style is", default_prompt)

        for style, phrase in style_expectations.items():
            with self.subTest(style=style):
                prompt = PromptBuilder.follow_up_system_prompt(prompt_style=style)
                self.assertIn(phrase, prompt)
                self.assertIn(disclaimer, prompt)

    def test_follow_up_prompt_omits_middle_of_long_analysis_and_truncates_question(self) -> None:
        analysis = "HEAD" + ("A" * 6100) + "MIDDLE_SENTINEL" + ("B" * 6100) + "TAIL_SENTINEL"
        question = ("Q" * 500) + "QUESTION_TAIL"

        prompt = PromptBuilder.follow_up_prompt(
            symbol="000001",
            analysis=analysis,
            question=question,
            report_meta={"template": "quick"},
        )

        self.assertIn("- Stock: 000001", prompt)
        self.assertIn("- Report meta: {'template': 'quick'}", prompt)
        self.assertIn("HEAD", prompt)
        self.assertIn("...[中间内容已省略]...", prompt)
        self.assertIn("TAIL_SENTINEL", prompt)
        self.assertNotIn("MIDDLE_SENTINEL", prompt)
        self.assertIn("\n" + ("Q" * 500) + "\n\n## Output Requirements", prompt)
        self.assertNotIn("QUESTION_TAIL", prompt)

    def test_analysis_prompt_minimal_data_marks_quote_and_kline_unavailable(self) -> None:
        prompt = PromptBuilder.analysis_prompt(
            symbol="000001",
            stock_data={
                "price": 0,
                "quote": {"source": "quote-db", "pe_ttm": 8.2, "pb": 0.9, "total_mv": 12_345},
            },
        )

        self.assertIn("- Focus: comprehensive analysis", prompt)
        self.assertIn("- Missing context: none", prompt)
        self.assertIn("- Latest price: 行情不可用 [source: quote-db]", prompt)
        self.assertIn("- Change pct: 不可用", prompt)
        self.assertIn("- Total market value: 1.23万元", prompt)
        self.assertIn("- K-line: unavailable. Do not infer short-term trend.", prompt)
        self.assertIn("- Revenue: N/A; YoY: N/A", prompt)

    def test_analysis_prompt_rich_data_limits_sections_and_keeps_trust_boundaries(self) -> None:
        stock_data = {
            "name": "Unit Bank",
            "price": "12.345",
            "change_pct": 1.234,
            "quote_source": "top-quote",
            "quote": {"source": "fallback-quote", "pe_ttm": 8.8, "pb": 0.7, "total_mv": 8_888},
            "financial": {
                "source": "unit-financials",
                "report_date": "2026Q1",
                "report_type": "quarterly",
                "pe_ttm": 10.1,
                "pb": 1.1,
                "total_mv": 150_000_000,
                "revenue": 12_345,
                "revenue_yoy": "7.891",
                "net_profit": 234_567_890,
                "net_profit_yoy": None,
                "eps": 0.45,
                "roe": 5.678,
                "roa": "bad",
                "total_assets": None,
                "total_liabilities": "invalid",
                "total_equity": 100,
                "operating_cf": -12_345,
                "gross_margin": 22.2,
                "net_margin": 33.333,
            },
            "kline_source": "unit-kline",
            "kline_data": [
                {
                    "date": f"KLINE-{idx:02d}",
                    "open": idx,
                    "high": idx + 1,
                    "low": idx - 1,
                    "close": idx + 0.5,
                    "change_pct": idx / 10,
                }
                for idx in range(1, 13)
            ],
            "indicators": {"ma5": 12.0, "empty": "", "missing": None},
            "announcements": [
                {"announce_date": f"ANNDATE-{idx}", "category": "notice", "title": f"ANN_TITLE_{idx}"}
                for idx in range(7)
            ],
            "news": [
                {"publish_time": f"NEWSDATE-{idx}", "title": f"NEWS_TITLE_{idx}", "source": f"Source {idx}"}
                for idx in range(7)
            ],
            "news_sentiment": {
                "total": 3,
                "positive": 1,
                "neutral": 1,
                "negative": 1,
                "count_dominant_sentiment": "neutral",
                "weighted_dominant_sentiment": "negative",
                "dominant_basis": "weighted",
                "avg_score": 0.12345,
                "validation_note": "weighted high-impact event dominates",
                "top_impact": [
                    {
                        "sentiment": "negative",
                        "title": f"IMPACT_TITLE_{idx}",
                        "impact_level": "high",
                        "sentiment_score": -0.8,
                    }
                    for idx in range(7)
                ],
            },
            "industry_event_context": {
                "available": True,
                "sector": "AI",
                "note": "sector only",
                "warnings": ["indirect only"],
                "themes": [
                    {
                        "theme": f"THEME_{idx}",
                        "direction": "positive",
                        "confidence": "medium",
                        "note": f"theme note {idx}",
                        "evidence": [
                            {
                                "publish_time": f"EVID_DATE_{idx}_{evidence_idx}",
                                "title": f"EVIDENCE_{idx}_{evidence_idx}",
                                "source": "sector-feed",
                                "related_sector": "AI",
                                "scope": "sector",
                            }
                            for evidence_idx in range(3)
                        ],
                    }
                    for idx in range(6)
                ],
            },
            "readiness": {
                "missing_context": ["peer valuation", "northbound"],
                "data_grade": {"grade": "B", "label": "partial", "analysis_scope": "limited scope"},
            },
            "data_quality": {"quote": "fresh"},
        }

        prompt = PromptBuilder.analysis_prompt(
            symbol="000001",
            stock_data=stock_data,
            question=("Q" * 310),
            framework="valuation",
            report_mode="detailed",
            report_template="professional",
            prompt_style="risk_control",
        )

        self.assertIn("- Prompt style: risk_control (风险排雷)", prompt)
        self.assertIn("- Report template: professional (专业深度版)", prompt)
        self.assertIn("- Focus: PE/PB, market value, valuation risk and margin of safety", prompt)
        self.assertIn("- User question: " + ("Q" * 300), prompt)
        self.assertNotIn("Q" * 301, prompt)
        self.assertIn("- Data grade: B (partial)", prompt)
        self.assertIn("- Missing context: peer valuation, northbound", prompt)
        self.assertIn("- Latest price: 12.35 [source: top-quote]", prompt)
        self.assertIn("- Change pct: 1.234%", prompt)
        self.assertIn("- Total market value: 1.50亿元", prompt)
        self.assertIn("- Indicators: {'ma5': 12.0}", prompt)
        self.assertIn("- Recent 10 daily K-lines:", prompt)
        self.assertNotIn("KLINE-01", prompt)
        self.assertIn("KLINE-03", prompt)
        self.assertIn("KLINE-12", prompt)
        self.assertIn("- Revenue: 1.23万元; YoY: 7.89%", prompt)
        self.assertIn("- Net profit attributable to parent: 2.35亿元; YoY: N/A", prompt)
        self.assertIn("- EPS: 0.45; ROE: 5.68%; ROA: N/A", prompt)
        self.assertIn("## Recent Announcements", prompt)
        self.assertIn("ANN_TITLE_5", prompt)
        self.assertNotIn("ANN_TITLE_6", prompt)
        self.assertIn("## Recent News", prompt)
        self.assertIn("NEWS_TITLE_5", prompt)
        self.assertIn("(source: Source 5)", prompt)
        self.assertNotIn("NEWS_TITLE_6", prompt)
        self.assertIn("## Sentiment Validation Summary", prompt)
        self.assertIn("- Average sentiment score: 0.123", prompt)
        self.assertIn("IMPACT_TITLE_5", prompt)
        self.assertNotIn("IMPACT_TITLE_6", prompt)
        self.assertIn("## Social / Policy / Industry Event Context", prompt)
        self.assertIn("- Warnings: indirect only", prompt)
        self.assertIn("THEME_4", prompt)
        self.assertNotIn("THEME_5", prompt)
        self.assertIn("EVIDENCE_0_1", prompt)
        self.assertNotIn("EVIDENCE_0_2", prompt)
        self.assertIn("- Use risk-control style: put invalidation conditions and warning signals before upside imagination.", prompt)
        self.assertIn("- Clearly separate 事实数据, 规则判断, 模型推断, 数据缺口, 风险声明, and 非投资建议边界.", prompt)

    def test_analysis_prompt_adds_each_style_output_requirement(self) -> None:
        style_expectations = {
            "plain": "Use plain-language style: avoid jargon stacking",
            "beginner": "Use beginner teaching style: add a small '小白翻译' line",
            "professional": "Use professional research style",
            "risk_control": "Use risk-control style: put invalidation conditions",
        }

        for style, phrase in style_expectations.items():
            with self.subTest(style=style):
                prompt = PromptBuilder.analysis_prompt(
                    symbol="000001",
                    stock_data={"price": 1},
                    prompt_style=style,
                )
                self.assertIn(f"- Prompt style: {style} ({PromptBuilder.PROMPT_STYLES[style]})", prompt)
                self.assertIn(phrase, prompt)

        default_prompt = PromptBuilder.analysis_prompt(
            symbol="000001",
            stock_data={"price": 1},
            prompt_style="default",
        )
        self.assertNotIn("- Prompt style:", default_prompt)
        self.assertNotIn("Use plain-language style: avoid jargon stacking", default_prompt)


if __name__ == "__main__":
    unittest.main()
