from __future__ import annotations

import re
from typing import Optional


def extract_code(symbol: str) -> str:
    match = re.search(r"\d{6}", (symbol or "").upper())
    return match.group(0) if match else ""


def extract_market(symbol: str) -> Optional[str]:
    text = (symbol or "").strip().upper()
    if "." in text:
        suffix = text.rsplit(".", 1)[1]
        return "SH" if suffix == "SS" else suffix
    for prefix in ("SH", "SZ", "BJ"):
        if text.startswith(prefix):
            return prefix
    return None


def infer_market(code: str, market: Optional[str] = None) -> str:
    normalized = (market or "").strip().upper()
    if normalized == "SS":
        normalized = "SH"
    if normalized in {"SH", "SZ", "BJ"}:
        return normalized
    if code.startswith(("4", "8", "920")):
        return "BJ"
    if code.startswith(("6", "9", "5")):
        return "SH"
    return "SZ"


def api_symbol(symbol: str, market: str = "") -> str:
    code = extract_code(symbol)
    if not code:
        return symbol or ""
    return f"{code}.{infer_market(code, market)}"


def bj_legacy_920_symbol(symbol: str, market: Optional[str] = None) -> str:
    code = extract_code(symbol)
    if len(code) != 6:
        return ""
    resolved_market = infer_market(code, market or extract_market(symbol))
    if resolved_market != "BJ" or code.startswith("920"):
        return ""
    if not code.startswith(("4", "8")):
        return ""
    return f"920{code[-3:]}.BJ"
