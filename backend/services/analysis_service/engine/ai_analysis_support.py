from __future__ import annotations

from datetime import date
import hashlib
import re
from typing import Any

from backend.services.analysis_service.engine.report_guard import ReportGuard


def analysis_cache_key(
    user_id: int,
    request: Any,
    report_mode: str,
    audience: str,
    report_template: str,
    prompt_style: str,
) -> str:
    raw = "|".join(
        [
            str(user_id),
            str(request.model_id),
            request.symbol,
            report_template,
            prompt_style,
            report_mode,
            audience,
            request.framework or "",
            request.question or "",
            str(request.include_news),
            date.today().isoformat(),
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def batch_item_cache_key(symbol: str, report_mode: str, audience: str, include_news: bool) -> str:
    raw = "|".join([symbol, report_mode, audience, str(include_news), date.today().isoformat()])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def prepare_cached_analysis_response(cached: dict | None, *, mark_hit: bool = True) -> dict | None:
    if not cached:
        return None

    prepared = dict(cached)
    if prepared.get("analysis"):
        prepared["analysis"], sanitized = ReportGuard.sanitize_advice_language(prepared["analysis"])
        if sanitized:
            report_meta = dict(prepared.get("report_meta") or {})
            report_meta["sanitized"] = True
            prepared["report_meta"] = report_meta

    if mark_hit:
        prepared["cache_hit"] = True
        if isinstance(prepared.get("report_meta"), dict):
            prepared["report_meta"] = dict(prepared["report_meta"])
            prepared["report_meta"]["force_refresh"] = False
    return prepared


def clean_model_analysis(content: str) -> tuple[str, bool]:
    guarded = ReportGuard.ensure_content(content)
    return ReportGuard.sanitize_advice_language(guarded)


def attach_trust_boundary_section(analysis: str, trust_boundary: dict) -> str:
    if not analysis:
        return analysis

    boundary_re = re.compile(
        r"(?ms)\n?##\s*(?:\u53ef\u4fe1\u8fb9\u754c|\u9359\u5d88\u7ed4\u6dc7\u5a07\u6f8d\u9423\u4f79\u7779)\s*\n.*?(?=\n##\s|\Z)"
    )
    source_re = re.compile(r"(?m)^##\s*(?:\u6570\u636e\u6765\u6e90|\u93c1\u7248\u5a4c\u93c9\u30e6\u7d1d)\s*$")
    section = ReportGuard.render_trust_boundary_section(trust_boundary)
    cleaned = boundary_re.sub("\n", analysis).strip()
    match = source_re.search(cleaned)
    if not match:
        return cleaned.rstrip() + "\n" + section

    main = cleaned[:match.start()].rstrip()
    source = cleaned[match.start():].lstrip()
    return main + "\n" + section + "\n" + source


def build_guarded_trust_analysis(
    analysis: str,
    stock_data: dict,
    risk_lights: dict,
    *,
    status: str,
    fallback_reason: str | None,
    sanitized: bool,
    trimmed: bool,
) -> tuple[str, dict]:
    trust_boundary = ReportGuard.build_trust_boundary(
        stock_data,
        risk_lights,
        status=status,
        fallback_reason=fallback_reason,
        sanitized=sanitized,
        trimmed=trimmed,
    )
    return attach_trust_boundary_section(analysis, trust_boundary), trust_boundary
