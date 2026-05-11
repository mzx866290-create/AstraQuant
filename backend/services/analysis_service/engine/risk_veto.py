from __future__ import annotations


_GRADE_ORDER = {"A": 4, "B": 3, "C": 2, "D": 1}
_VALID_SEVERITIES = {"hard", "soft"}
_IMMUTABLE_HARD_TYPES = {
    "st_risk",
    "delisting_risk",
    "data_grade_unusable",
    "data_grade_below_strategy_minimum",
    "critical_market_data_missing",
}


def _grade_value(grade: str | None) -> int:
    return _GRADE_ORDER.get((grade or "D").upper(), 0)


def _normalize_severity(value: object, default: str) -> str:
    severity = str(value or default).lower()
    return severity if severity in _VALID_SEVERITIES else default


def _policy_entry(policy: dict, risk_key: str, risk_type: str) -> dict:
    by_key = policy.get("by_key") or {}
    by_type = policy.get("by_type") or {}
    entry = by_key.get(risk_key, by_type.get(risk_type, {}))
    if isinstance(entry, str):
        return {"severity": entry}
    return entry if isinstance(entry, dict) else {}


def _risk_item(
    *,
    risk_key: str,
    risk_type: str,
    default_severity: str,
    detail: str,
    policy: dict,
    immutable_hard: bool = False,
) -> dict:
    entry = _policy_entry(policy, risk_key, risk_type)
    severity = _normalize_severity(entry.get("severity"), default_severity)
    if immutable_hard or risk_type in _IMMUTABLE_HARD_TYPES:
        severity = "hard"

    item = {
        "type": risk_type,
        "severity": severity,
        "detail": detail,
    }
    if risk_key != risk_type:
        item["key"] = risk_key
    if "score_delta" in entry:
        item["score_delta"] = entry["score_delta"]
    if entry.get("handling"):
        item["handling"] = entry["handling"]
    return item


def _append_by_severity(item: dict, vetoes: list[dict], warnings: list[dict]) -> None:
    if item.get("severity") == "hard":
        vetoes.append(item)
    else:
        warnings.append(item)


def evaluate_risk_veto(stock_data: dict, risk_lights: dict, strategy: dict | None = None) -> dict:
    strategy = strategy or {}
    risk_policy = strategy.get("risk_policy") or {}
    readiness = stock_data.get("readiness") or {}
    data_grade = (readiness.get("data_grade") or {}).get("grade", "D")
    raw_name = str(stock_data.get("name") or stock_data.get("symbol") or "").strip()
    normalized_name = raw_name.replace(" ", "").upper()
    financial = stock_data.get("financial") or {}

    vetoes: list[dict] = []
    warnings: list[dict] = []

    min_data_grade = str((strategy.get("filters") or {}).get("min_data_grade") or "D").upper()
    if str(data_grade).upper() == "D":
        vetoes.append(
            _risk_item(
                risk_key="data_grade_unusable",
                risk_type="data_grade_unusable",
                default_severity="hard",
                detail=f"Data grade {data_grade} is unusable for risk gating",
                policy=risk_policy,
                immutable_hard=True,
            )
        )
    if _grade_value(data_grade) < _grade_value(min_data_grade):
        vetoes.append(
            _risk_item(
                risk_key="data_grade_below_strategy_minimum",
                risk_type="data_grade_below_strategy_minimum",
                default_severity="hard",
                detail=f"Data grade {data_grade} is below strategy minimum {min_data_grade}",
                policy=risk_policy,
                immutable_hard=True,
            )
        )

    if normalized_name.startswith(("ST", "*ST", "S*ST")):
        vetoes.append(
            _risk_item(
                risk_key="st_risk",
                risk_type="st_risk",
                default_severity="hard",
                detail="Stock name contains ST marker",
                policy=risk_policy,
                immutable_hard=True,
            )
        )
    if "退" in raw_name:
        vetoes.append(
            _risk_item(
                risk_key="delisting_risk",
                risk_type="delisting_risk",
                default_severity="hard",
                detail="Stock name indicates delisting risk",
                policy=risk_policy,
                immutable_hard=True,
            )
        )

    price_missing = "price" in stock_data and stock_data.get("price") in (None, "", 0)
    kline_missing = "kline_data" in stock_data and not stock_data.get("kline_data")
    if price_missing or kline_missing:
        vetoes.append(
            _risk_item(
                risk_key="critical_market_data_missing",
                risk_type="critical_market_data_missing",
                default_severity="hard",
                detail="Critical price or kline data is missing",
                policy=risk_policy,
                immutable_hard=True,
            )
        )

    default_red_severity = _normalize_severity(risk_policy.get("default_red_severity"), "hard")
    default_yellow_severity = _normalize_severity(risk_policy.get("default_yellow_severity"), "soft")
    for key, item in (risk_lights or {}).items():
        level = str(item.get("level") or "").lower()
        risk_key = str(key)
        risk_type = str(item.get("type") or risk_key)
        if level == "red":
            _append_by_severity(
                _risk_item(
                    risk_key=risk_key,
                    risk_type=risk_type,
                    default_severity=default_red_severity,
                    detail=item.get("message") or f"{risk_key} red light",
                    policy=risk_policy,
                ),
                vetoes,
                warnings,
            )
        elif level == "yellow":
            _append_by_severity(
                _risk_item(
                    risk_key=risk_key,
                    risk_type=risk_type,
                    default_severity=default_yellow_severity,
                    detail=item.get("message") or f"{risk_key} yellow light",
                    policy=risk_policy,
                ),
                vetoes,
                warnings,
            )

    operating_cf = financial.get("operating_cf")
    if operating_cf is not None:
        try:
            if float(operating_cf) < 0:
                _append_by_severity(
                    _risk_item(
                        risk_key="negative_operating_cashflow",
                        risk_type="negative_operating_cashflow",
                        default_severity="soft",
                        detail="Operating cash flow is negative",
                        policy=risk_policy,
                    ),
                    vetoes,
                    warnings,
                )
        except (TypeError, ValueError):
            pass

    profit_yoy = financial.get("net_profit_yoy")
    revenue_yoy = financial.get("revenue_yoy")
    try:
        if revenue_yoy is not None and profit_yoy is not None and float(revenue_yoy) < 0 and float(profit_yoy) < 0:
            _append_by_severity(
                _risk_item(
                    risk_key="financial_deterioration",
                    risk_type="financial_deterioration",
                    default_severity="soft",
                    detail="Revenue and profit yoy are both negative",
                    policy=risk_policy,
                ),
                vetoes,
                warnings,
            )
    except (TypeError, ValueError):
        pass

    passed = len(vetoes) == 0
    return {
        "passed": passed,
        "level": "none" if passed and not warnings else "soft" if passed else "hard",
        "veto_reason": vetoes[0]["type"] if vetoes else None,
        "vetoes": vetoes,
        "warnings": warnings,
    }
