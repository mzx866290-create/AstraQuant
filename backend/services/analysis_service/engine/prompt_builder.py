from __future__ import annotations

from typing import Any


def fmt_billion(val: Any) -> str:
    if val is None:
        return "N/A"
    try:
        value = float(val)
    except (TypeError, ValueError):
        return "N/A"
    if abs(value) >= 1e8:
        return f"{value / 1e8:.2f}亿元"
    if abs(value) >= 1e4:
        return f"{value / 1e4:.2f}万元"
    return f"{value:.2f}"


def fmt_pct(val: Any) -> str:
    if val is None:
        return "N/A"
    try:
        return f"{float(val):.2f}%"
    except (TypeError, ValueError):
        return "N/A"


def fmt_price(val: Any) -> str:
    try:
        value = float(val)
    except (TypeError, ValueError):
        return "行情不可用"
    if value == 0.0:
        return "行情不可用"
    return f"{value:.2f}"


class PromptBuilder:
    REPORT_TEMPLATES = {
        "quick": "快速诊断版",
        "professional": "专业深度版",
        "teaching": "投资者教学版",
    }
    PROMPT_STYLES = {
        "default": "默认",
        "plain": "通俗易懂",
        "beginner": "小白教学",
        "professional": "专业投研",
        "risk_control": "风险排雷",
    }

    @staticmethod
    def normalize_report_mode(report_mode: str | None) -> str:
        return report_mode if report_mode in ("summary", "detailed") else "summary"

    @staticmethod
    def normalize_report_template(report_template: str | None) -> str:
        return report_template if report_template in PromptBuilder.REPORT_TEMPLATES else "quick"

    @staticmethod
    def normalize_audience(audience: str | None) -> str:
        return audience if audience in ("normal", "beginner") else "normal"

    @staticmethod
    def normalize_prompt_style(prompt_style: str | None, audience: str | None = None) -> str:
        if prompt_style in (None, "", "default"):
            return "default"
        if prompt_style in PromptBuilder.PROMPT_STYLES:
            return prompt_style
        if audience == "beginner":
            return "beginner"
        return "default"

    @staticmethod
    def model_config(report_mode: str, report_template: str = "quick") -> dict:
        if report_template == "professional":
            return {"temperature": 0.25, "timeout": 240, "max_retries": 0, "max_tokens": 3600}
        if report_template == "teaching":
            return {"temperature": 0.28, "timeout": 240, "max_retries": 0, "max_tokens": 3800}
        if report_mode == "detailed":
            return {"temperature": 0.3, "timeout": 150, "max_retries": 0, "max_tokens": 1800}
        return {"temperature": 0.25, "timeout": 90, "max_retries": 0, "max_tokens": 950}

    @staticmethod
    def follow_up_config() -> dict:
        return {"temperature": 0.25, "timeout": 90, "max_retries": 0, "max_tokens": 1000}

    @staticmethod
    def system_prompt(
        report_mode: str = "summary",
        audience: str = "normal",
        report_template: str = "quick",
        prompt_style: str = "default",
        custom_prompt: str | None = None,
    ) -> str:
        report_template = PromptBuilder.normalize_report_template(report_template)
        prompt_style = PromptBuilder.normalize_prompt_style(prompt_style, audience)
        length_rule = (
            "Quick template: 600-1000 Chinese characters, short, concrete, and easy to scan."
            if report_template == "quick"
            else (
                "Professional template: 3000-5200 Chinese characters. Cover the required sections, but shorten sections whose data is missing."
                if report_template == "professional"
                else "Teaching template: 3000-5600 Chinese characters. Explain the research logic and tracking checklist in plain, practical language."
            )
        )
        style_rule = PromptBuilder._prompt_style_rule(prompt_style)
        style_rule_line = f"- {style_rule}" if style_rule else ""
        section_rule = PromptBuilder._template_section_rule(report_template)
        base = f"""You are a professional A-share equity analyst. Output must be Simplified Chinese Markdown.

Hard rules:
- {length_rule}
{style_rule_line}
- Use only the structured data provided in the user message.
- Never treat price 0, missing K-line, missing PE/PB, or stale data as valid evidence.
- If 5-year financials, valuation percentiles, peer comparison, northbound holdings, market share, or institutional ownership are not provided, explicitly write "数据缺失/无法判断" instead of filling the gap from memory.
- Separate count-dominant sentiment from weighted-dominant sentiment. If neutral news is the count majority, do not say negative dominates unless the weighted high-impact events are negative and you explain that basis.
- Social, policy, and industry news are indirect sector context only. Never write them as company facts, announcements, orders, or confirmed earnings drivers.
- Do not invent price, K-line, PE/PB, industry averages, comparable companies, announcements, policy details, holdings, or news events.
- Separate facts, analyst judgment, and data gaps.
- Use watch/track/risk wording. Do not give personalized buy/sell instructions or direct position commands.
- For investment decision language, use research labels such as 观察、谨慎观察、风险偏高、暂不具备判断条件.
- Make the trust boundary explicit: label 事实数据、规则判断、模型推断、数据缺口、风险声明、非投资建议边界 where relevant.
- End with a short risk disclaimer.

Report template:
{section_rule}
"""
        if custom_prompt:
            return base + "\nAdditional admin instruction:\n" + custom_prompt[:1200]
        return base

    @staticmethod
    def follow_up_system_prompt(audience: str = "normal", prompt_style: str = "default") -> str:
        prompt_style = PromptBuilder.normalize_prompt_style(prompt_style, audience)
        style_rule = PromptBuilder._prompt_style_rule(prompt_style)
        style_rule_line = f"- {style_rule}\n" if style_rule else ""
        return f"""You are a professional A-share analyst and patient investor tutor. Output Simplified Chinese Markdown.

Hard rules:
- Answer only the user's follow-up question using the provided prior report.
{style_rule_line}- Do not invent prices, valuation percentiles, financial data, policies, holdings, or news not present in the prior report.
- If the prior report lacks enough evidence, say "原报告数据不足，无法判断" and explain what data should be checked.
- Explain jargon in practical language when the user seems confused.
- If the user asks whether to buy/sell/add/reduce, convert it into a non-personal decision framework: watch points, invalidation conditions, and risk reminders.
- Keep the answer within 400-900 Chinese characters unless the user asks for a very short answer.
- End with: 以上解读仅供学习和参考，不构成投资建议。
"""

    @staticmethod
    def follow_up_prompt(
        symbol: str,
        analysis: str,
        question: str,
        report_meta: dict | None = None,
    ) -> str:
        trimmed_analysis = (analysis or "").strip()
        if len(trimmed_analysis) > 12000:
            trimmed_analysis = trimmed_analysis[:6000].rstrip() + "\n\n...[中间内容已省略]...\n\n" + trimmed_analysis[-5000:].lstrip()
        return "\n".join(
            [
                "## Task",
                "Answer the follow-up question based on the prior AI analysis report below.",
                f"- Stock: {symbol}",
                f"- Report meta: {report_meta or {}}",
                "- Prior report trust: client-provided conversation context, not a server-verified source of truth.",
                "- Treat the prior report as unverified unless it contains explicit data source and trust boundary evidence.",
                "",
                "## Prior Report",
                trimmed_analysis,
                "",
                "## User Follow-up Question",
                question[:500],
                "",
                "## Output Requirements",
                "- Be direct, practical, and easy to understand.",
                "- Quote or paraphrase the relevant part of the prior report briefly, then explain it.",
                "- Do not repeat the whole report.",
                "- Do not provide personalized buy/sell instructions.",
            ]
        )

    @staticmethod
    def _prompt_style_rule(prompt_style: str) -> str:
        if prompt_style == "plain":
            return (
                "Prompt style is plain-language: write for ordinary retail investors. "
                "Use short sentences, explain every market term the first time it appears, and translate conclusions into '看什么、为什么、怎么跟踪'."
            )
        if prompt_style == "beginner":
            return (
                "Prompt style is beginner teaching: assume the reader has little finance background. "
                "After PE/PB/ROE/cash flow/valuation terms, add a simple explanation in parentheses and avoid dense jargon."
            )
        if prompt_style == "professional":
            return (
                "Prompt style is professional research: use concise sell-side research language, but still separate facts, judgment, and data gaps."
            )
        if prompt_style == "risk_control":
            return (
                "Prompt style is risk-control first: prioritize downside risks, invalidation conditions, warning signs, and what data must be tracked next."
            )
        return ""

    @staticmethod
    def _template_section_rule(report_template: str) -> str:
        if report_template == "professional":
            return """Use exactly these sections:
1. 公司概况与业务模式
2. 财务健康分析
3. 竞争格局与护城河
4. 估值分析
5. 政策与宏观环境
6. 催化剂与风险地图
7. 牛熊案例
8. 投资决策框架（非投资建议）"""
        if report_template == "teaching":
            return """Use exactly these sections:
1. 卷首语：分析师的投研教学
2. 基本面拆解
3. 财务体检与异常解释
4. 估值方法教学
5. 风险地图与情景推演
6. 投资者实战跟踪框架
7. 财报季必看清单
8. 纪律触发器与免责声明"""
        return """Use exactly these sections:
1. 先说结论
2. 为什么这么看
3. 最大风险
4. 普通投资者盯什么
5. 数据缺口与免责声明"""

    @staticmethod
    def analysis_prompt(
        symbol: str,
        stock_data: dict,
        question: str | None = None,
        framework: str | None = None,
        report_mode: str = "summary",
        audience: str = "normal",
        report_template: str = "quick",
        prompt_style: str = "default",
    ) -> str:
        report_template = PromptBuilder.normalize_report_template(report_template)
        prompt_style = PromptBuilder.normalize_prompt_style(prompt_style, audience)
        framework_labels = {
            "technical": "technical trend, volume-price action, moving averages, support/resistance",
            "fundamental": "earnings quality, balance sheet, growth, cash flow",
            "valuation": "PE/PB, market value, valuation risk and margin of safety",
            "event": "announcements, news, policy, and short-term event impact",
        }
        is_detailed = report_mode == "detailed" or report_template in ("professional", "teaching")
        kline_limit = 10 if is_detailed else 5
        news_limit = 6 if is_detailed else 3
        ann_limit = 6 if is_detailed else 3

        name = stock_data.get("name", symbol)
        quote = stock_data.get("quote") or {}
        financial = stock_data.get("financial") or {}
        sentiment = stock_data.get("news_sentiment") or {}
        kline = stock_data.get("kline_data") or []
        indicators = stock_data.get("indicators") or {}
        announcements = stock_data.get("announcements") or []
        news = stock_data.get("news") or []
        industry_event = stock_data.get("industry_event_context") or {}
        readiness = stock_data.get("readiness") or {}
        data_quality = stock_data.get("data_quality") or {}

        missing = readiness.get("missing_context") or []
        data_grade = readiness.get("data_grade") or {}
        price_text = fmt_price(stock_data.get("price"))
        change_text = "不可用" if price_text == "行情不可用" else f"{stock_data.get('change_pct', 'N/A')}%"
        lines = [
            "## Task",
            "Generate an A-share stock analysis report from the structured data below.",
            f"- Report template: {report_template} ({PromptBuilder.REPORT_TEMPLATES[report_template]})",
            f"- Report mode: {report_mode}",
            f"- Audience: {audience}",
            f"- Stock: {symbol} {name}",
            f"- Focus: {framework_labels.get(framework, 'comprehensive analysis')}",
        ]
        if prompt_style != "default":
            lines.insert(3, f"- Prompt style: {prompt_style} ({PromptBuilder.PROMPT_STYLES[prompt_style]})")
        if question:
            lines.append(f"- User question: {question[:300]}")

        lines.extend([
            "",
            "## Data Readiness",
            f"- Data grade: {data_grade.get('grade', 'unknown')} ({data_grade.get('label', 'unknown')})",
            f"- Allowed analysis scope: {data_grade.get('analysis_scope', 'Follow missing data constraints.')}",
            f"- Missing context: {', '.join(missing) if missing else 'none'}",
            f"- Data quality: {data_quality}",
            "",
            "## Quote and Technical Data",
            f"- Latest price: {price_text} [source: {stock_data.get('quote_source') or quote.get('source') or 'none'}]",
            f"- Change pct: {change_text}",
            f"- PE(TTM): {financial.get('pe_ttm', quote.get('pe_ttm', 'N/A'))}",
            f"- PB: {financial.get('pb', quote.get('pb', 'N/A'))}",
            f"- Total market value: {fmt_billion(financial.get('total_mv') or quote.get('total_mv'))}",
            f"- K-line source: {stock_data.get('kline_source') or 'none'}",
        ])
        if indicators:
            compact_indicators = {k: v for k, v in indicators.items() if v not in (None, "")}
            lines.append(f"- Indicators: {compact_indicators}")
        if kline:
            lines.append(f"- Recent {kline_limit} daily K-lines:")
            for item in kline[-kline_limit:]:
                lines.append(
                    f"  - {item.get('date')}: open {item.get('open')}, high {item.get('high')}, "
                    f"low {item.get('low')}, close {item.get('close')}, change {item.get('change_pct', 'N/A')}%"
                )
        else:
            lines.append("- K-line: unavailable. Do not infer short-term trend.")

        lines.extend([
            "",
            f"## Financial Data [source: {financial.get('source', 'financial DB')}, period: {financial.get('report_date', 'N/A')}]",
            f"- Report type: {financial.get('report_type', 'N/A')}",
            f"- Revenue: {fmt_billion(financial.get('revenue'))}; YoY: {fmt_pct(financial.get('revenue_yoy'))}",
            f"- Net profit attributable to parent: {fmt_billion(financial.get('net_profit'))}; YoY: {fmt_pct(financial.get('net_profit_yoy'))}",
            f"- EPS: {financial.get('eps', 'N/A')}; ROE: {fmt_pct(financial.get('roe'))}; ROA: {fmt_pct(financial.get('roa'))}",
            f"- Total assets: {fmt_billion(financial.get('total_assets'))}; liabilities: {fmt_billion(financial.get('total_liabilities'))}; equity: {fmt_billion(financial.get('total_equity'))}",
            f"- Operating cash flow: {fmt_billion(financial.get('operating_cf'))}",
            f"- Gross margin: {fmt_pct(financial.get('gross_margin'))}; net margin: {fmt_pct(financial.get('net_margin'))}",
        ])

        if announcements:
            lines.extend(["", "## Recent Announcements"])
            for item in announcements[:ann_limit]:
                lines.append(f"- [{item.get('announce_date', '')}] [{item.get('category', 'announcement')}] {item.get('title', '')}")

        if news:
            lines.extend(["", "## Recent News"])
            for item in news[:news_limit]:
                line = f"- [{item.get('publish_time', '')}] {item.get('title', '')}"
                if item.get("source"):
                    line += f" (source: {item.get('source')})"
                lines.append(line)

        if sentiment and sentiment.get("total", 0) > 0:
            lines.extend([
                "",
            "## Sentiment Validation Summary",
                f"- News count in recent 7 days: {sentiment.get('total', 0)}",
                f"- Count distribution: positive {sentiment.get('positive', 0)} / neutral {sentiment.get('neutral', 0)} / negative {sentiment.get('negative', 0)}",
                f"- Count-dominant sentiment: {sentiment.get('count_dominant_sentiment', sentiment.get('dominant_sentiment', 'N/A'))}",
                f"- Weighted-dominant sentiment: {sentiment.get('weighted_dominant_sentiment', sentiment.get('dominant_sentiment', 'N/A'))}",
                f"- Dominant basis: {sentiment.get('dominant_basis', 'count')}",
                f"- Average sentiment score: {sentiment.get('avg_score', 0):.3f}",
                f"- Validation note: {sentiment.get('validation_note', '')}",
            ])
            for evt in (sentiment.get("top_impact") or [])[:news_limit]:
                lines.append(
                    f"  - High-impact: [{evt.get('sentiment', '')}] {evt.get('title', '')} "
                    f"(impact: {evt.get('impact_level', '')}, score: {evt.get('sentiment_score', 0):.2f})"
                )

        if industry_event:
            lines.extend([
                "",
                "## Social / Policy / Industry Event Context",
                f"- Available: {industry_event.get('available', False)}",
                f"- Sector: {industry_event.get('sector') or 'N/A'}",
                f"- Rule note: {industry_event.get('note', '')}",
            ])
            warnings = industry_event.get("warnings") or []
            if warnings:
                lines.append(f"- Warnings: {', '.join(warnings)}")
            for theme in (industry_event.get("themes") or [])[: 5 if is_detailed else 3]:
                lines.append(
                    f"- Theme: {theme.get('theme')} | direction: {theme.get('direction')} | "
                    f"confidence: {theme.get('confidence')} | note: {theme.get('note')}"
                )
                for evidence in (theme.get("evidence") or [])[:2]:
                    lines.append(
                        f"  - Evidence: [{evidence.get('publish_time', '')}] {evidence.get('title', '')} "
                        f"(source: {evidence.get('source', '')}, sector: {evidence.get('related_sector', '')}, scope: {evidence.get('scope', '')})"
                    )

        style_requirements = PromptBuilder._prompt_style_output_requirements(prompt_style)
        lines.extend([
            "",
            "## Output Requirements",
            "- Keep within the requested length band.",
            "- Quick template must start with exactly five short bullets: can analyze or not, main watch point, biggest risk, data gaps, next tracking condition. After the bullets, use the required quick sections.",
            "- Professional template must follow the 8-section structure and use '数据缺失/无法判断' for unavailable market share, peer valuation, historical percentile, northbound, or 5-year fields.",
            "- Teaching template must include practical tracking tools, explain why each key metric matters, and avoid turning methodology into personalized advice.",
            *style_requirements,
            "- If data grade is B or C, do not write a full fundamental conclusion; say fundamentals are partially unavailable.",
            "- If data grade is D, focus on data gaps and do not infer trend, valuation, or fundamentals.",
            "- Include risk lights: data risk, valuation risk, financial risk, news risk, technical risk.",
            "- Clearly separate 事实数据, 规则判断, 模型推断, 数据缺口, 风险声明, and 非投资建议边界.",
            "- In beginner audience, briefly explain what PE/PB and cash-flow mismatch mean.",
            "- If valuation data is missing, say valuation cannot be judged.",
            "- Discuss social/policy/industry events separately from stock-specific news, and label them as indirect sector clues.",
            "- End with: AI分析仅供参考，不构成投资建议；投资有风险，请结合自身情况和专业意见独立决策。",
        ])
        return "\n".join(lines)

    @staticmethod
    def _prompt_style_output_requirements(prompt_style: str) -> list[str]:
        if prompt_style == "plain":
            return [
                "- Use plain-language style: avoid jargon stacking; explain terms like PE/PB/ROE/现金流/估值 the first time they appear.",
                "- Translate each important conclusion into '看什么、为什么、怎么跟踪'.",
            ]
        if prompt_style == "beginner":
            return [
                "- Use beginner teaching style: add a small '小白翻译' line when discussing valuation, cash flow, or risk lights.",
                "- Use short sentences and explain terms like PE/PB/ROE/现金流/估值 in parentheses.",
            ]
        if prompt_style == "professional":
            return [
                "- Use professional research style, but keep facts, analyst judgment, and data gaps clearly separated.",
            ]
        if prompt_style == "risk_control":
            return [
                "- Use risk-control style: put invalidation conditions and warning signals before upside imagination.",
                "- Make the stop/review triggers objective and data-based, not price-only.",
            ]
        return []
