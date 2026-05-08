from __future__ import annotations

import re


class ReportGuard:
    LIMITS = {
        "summary": 1400,
        "detailed": 4200,
        "quick": 1400,
        "professional": 7800,
        "teaching": 8600,
    }
    DIRECT_ADVICE_REPLACEMENTS = (
        (re.compile(r"\u5efa\u8bae\s*(?:\u4e70\u5165|\u5356\u51fa|\u5efa\u4ed3|\u6e05\u4ed3|\u52a0\u4ed3|\u51cf\u4ed3|\u6301\u6709)"), "\u89c2\u5bdf\u6761\u4ef6\u548c\u98ce\u9669\u8fb9\u754c"),
        (re.compile(r"(?:\u4e70\u5165|\u5356\u51fa|\u5efa\u4ed3|\u6e05\u4ed3|\u52a0\u4ed3|\u51cf\u4ed3|\u6ee1\u4ed3|\u6284\u5e95|\u6301\u6709)"), "\u89c2\u5bdf\u6761\u4ef6"),
        (re.compile(r"(?:\u4ed3\u4f4d|\u6301\u4ed3)\s*(?:\u63d0\u9ad8|\u63d0\u5347|\u589e\u52a0|\u964d\u4f4e|\u964d\u5230|\u63a7\u5236|\u8c03\u6574)?\s*(?:\u5230|\u81f3)?\s*\d{1,3}\s*%?"), "\u98ce\u9669\u66b4\u9732\u9700\u72ec\u7acb\u8bc4\u4f30"),
        (re.compile(r"(?:\u76ee\u6807\u4ef7|\u76ee\u6807\u4f4d|\u6b62\u76c8\u4f4d|\u6b62\u635f\u4f4d|\u6b62\u76c8|\u6b62\u635f)"), "\u98ce\u9669\u89c2\u5bdf\u9608\u503c"),
        (re.compile(r"\u5f3a\u70c8\u63a8\u8350"), "\u91cd\u70b9\u5173\u6ce8"),
        (re.compile(r"建议\s*(买入|卖出|建仓|清仓|加仓|减仓|持有)"), "建议改为观察条件和风险边界"),
        (re.compile(r"(买入|卖出|建仓|清仓|加仓|减仓|满仓|抄底|持有)"), "观察条件"),
        (re.compile(r"(仓位|持仓)\s*(提高|提升|增加|降低|降到|控制|调整)?\s*(到|至)?\s*\d{1,3}\s*%?"), "风险暴露需独立评估"),
        (re.compile(r"(目标价|目标位|止盈位|止损位|止盈|止损)"), "风险观察阈值"),
        (re.compile(r"强烈推荐"), "重点关注"),
        (re.compile(r"(不|不要|不宜|不建议)\s*买入"), "暂不具备交易判断条件"),
        (re.compile(r"(不|不要|不宜|不建议)\s*卖出"), "暂不具备交易判断条件"),
        (re.compile(r"建议\s*买入"), "建议继续观察"),
        (re.compile(r"建议\s*卖出"), "建议继续观察"),
        (re.compile(r"强烈推荐"), "重点关注"),
        (re.compile(r"买入"), "继续观察"),
        (re.compile(r"卖出"), "继续观察"),
        (re.compile(r"目标价"), "参考价"),
        (re.compile(r"满仓"), "高仓位"),
        (re.compile(r"清仓"), "降低至零仓位"),
        (re.compile(r"加仓"), "增加关注"),
        (re.compile(r"减仓"), "降低敞口"),
        (re.compile(r"抄底"), "逆势博弈"),
        (re.compile(r"止盈"), "风险控制阈值"),
        (re.compile(r"止损"), "风险控制阈值"),
        (re.compile(r"\bstrong\s+buy\b", re.IGNORECASE), "watch closely"),
        (re.compile(r"\bbuy\b", re.IGNORECASE), "observe"),
        (re.compile(r"\bsell\b", re.IGNORECASE), "observe"),
        (re.compile(r"\btarget\s+price\b", re.IGNORECASE), "reference price"),
        (re.compile(r"\bfull\s+position\b", re.IGNORECASE), "high exposure"),
        (re.compile(r"\bclear\s+position\b", re.IGNORECASE), "reduce exposure"),
        (re.compile(r"\badd\s+position\b", re.IGNORECASE), "increase attention"),
        (re.compile(r"\breduce\s+position\b", re.IGNORECASE), "reduce exposure"),
        (re.compile(r"\bstop\s*loss\b", re.IGNORECASE), "risk-control threshold"),
        (re.compile(r"\btake\s*profit\b", re.IGNORECASE), "risk-control threshold"),
    )

    @classmethod
    def ensure_content(cls, content: str) -> str:
        text = (content or "").strip()
        if len(text) < 40:
            raise RuntimeError("AI model returned an empty or too-short report")
        return text

    @classmethod
    def sanitize_advice_language(cls, content: str) -> tuple[str, bool]:
        text = content or ""
        sanitized = text
        changed = False
        for pattern, replacement in cls.DIRECT_ADVICE_REPLACEMENTS:
            sanitized, count = pattern.subn(replacement, sanitized)
            changed = changed or count > 0
        return sanitized, changed

    @classmethod
    def _available_sources(cls, stock_data: dict) -> list[str]:
        sources = []
        if stock_data.get("quote"):
            sources.append("实时行情")
        if stock_data.get("kline_data"):
            sources.append("K线")
        if stock_data.get("financial"):
            sources.append("财务")
        if stock_data.get("announcements"):
            sources.append("公告")
        if stock_data.get("news"):
            sources.append("新闻")
        if (stock_data.get("industry_event_context") or {}).get("themes"):
            sources.append("行业事件")
        return sources

    @classmethod
    def build_trust_boundary(
        cls,
        stock_data: dict,
        risk_lights: dict,
        *,
        status: str,
        fallback_reason: str | None = None,
        sanitized: bool = False,
        trimmed: bool = False,
    ) -> dict:
        readiness = stock_data.get("readiness") or {}
        data_grade = readiness.get("data_grade") or {}
        missing = [str(item) for item in (readiness.get("missing_context") or []) if item]
        sources = cls._available_sources(stock_data)
        facts = [
            f"数据等级：{data_grade.get('grade', 'N/A')} · {data_grade.get('label', '数据不足')}",
            f"分析范围：{data_grade.get('analysis_scope') or '仅限当前结构化数据'}",
            f"可用来源：{'、'.join(sources) if sources else '暂无'}",
        ]
        if missing:
            facts.append(f"主要缺口：{'、'.join(missing[:5])}")

        rules = [
            {
                "key": key,
                "label": item.get("label", key),
                "level": item.get("level", "yellow"),
                "message": item.get("message", ""),
            }
            for key, item in (risk_lights or {}).items()
        ]

        model = [
            f"模型状态：{'AI生成' if status == 'success' else '本地规则兜底'}",
            f"后处理：{'已进行合规清洗' if sanitized else '未触发清洗'}",
            f"长度处理：{'已压缩' if trimmed else '未压缩'}",
        ]
        if fallback_reason:
            model.append(f"兜底说明：{fallback_reason[:180]}")

        limits = [
            "只使用公开结构化数据和当前上下文",
            "缺失项会明确标注无法判断，不补脑",
            "不提供个性化买卖、加减仓或仓位指令",
            "AI分析仅供参考，不构成投资建议",
        ]

        return {
            "facts": facts,
            "rules": rules,
            "model": model,
            "limits": limits,
            "status": status,
            "sanitized": sanitized,
            "trimmed": trimmed,
        }

    @classmethod
    def render_trust_boundary_section(cls, trust_boundary: dict) -> str:
        facts = trust_boundary.get("facts") or []
        rules = trust_boundary.get("rules") or []
        model = trust_boundary.get("model") or []
        limits = trust_boundary.get("limits") or []

        facts_text = "；".join(facts[:3]) if facts else "仅依据当前结构化数据"
        rules_text = " / ".join(
            f"{item.get('label', '风险项')}({item.get('level', 'yellow')})"
            for item in rules[:3]
        ) if rules else "数据、估值、财务、消息、技术风险已单独评估"
        model_text = "；".join(model[:2]) if model else "仅解释已有数据，不补缺口"
        limit_text = "；".join(limits[:2]) if limits else "不提供个性化买卖指令"

        return "\n".join(
            [
                "",
                "## 可信边界",
                f"- 事实数据：{facts_text}",
                f"- 规则判断：{rules_text}",
                f"- 模型推断：{model_text}",
                f"- 风险与限制：{limit_text}",
                f"- 非投资建议边界：{limits[-1] if limits else 'AI分析仅供参考，不构成投资建议'}",
            ]
        )

    @classmethod
    def enforce_length(cls, analysis: str, report_mode: str, report_template: str | None = None) -> tuple[str, bool]:
        limit_key = report_template if report_template in cls.LIMITS else report_mode
        limit = cls.LIMITS.get(limit_key, cls.LIMITS["summary"])
        source_marker = "\n## 数据来源\n"
        if source_marker in analysis:
            main, source = analysis.split(source_marker, 1)
            source = source_marker + source
        else:
            main, source = analysis, ""

        if len(main) <= limit:
            return analysis, False

        cut_at = main.rfind("\n", 0, limit)
        if cut_at < int(limit * 0.65):
            cut_at = limit
        trimmed = main[:cut_at].rstrip()
        trimmed += "\n\n> 报告已按当前模式自动压缩，避免输出过长；如需更多细节请切换展开版或缩小分析问题。"
        return trimmed + source, True
