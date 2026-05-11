from __future__ import annotations


def _strength_from_impact(impact: int) -> str:
    magnitude = abs(int(impact or 0))
    if magnitude >= 12:
        return "strong"
    if magnitude >= 5:
        return "moderate"
    return "weak"


def _factor_label(item: dict) -> str:
    return str(item.get("label") or item.get("factor") or "未命名因子")


def build_debate_view(
    stock_data: dict,
    evidence_chain: list[dict],
    veto_result: dict,
    strategy: dict,
) -> dict:
    positive = [item for item in evidence_chain if int(item.get("impact") or 0) > 0 and item.get("factor") != "base"]
    negative = [item for item in evidence_chain if int(item.get("impact") or 0) < 0]

    positive.sort(key=lambda item: abs(int(item.get("impact") or 0)), reverse=True)
    negative.sort(key=lambda item: abs(int(item.get("impact") or 0)), reverse=True)

    bull_case = [
        {
            "factor": item.get("factor"),
            "argument": f"{_factor_label(item)}：{item.get('explanation')}",
            "strength": _strength_from_impact(int(item.get("impact") or 0)),
        }
        for item in positive[:3]
    ]
    bear_case = [
        {
            "factor": item.get("factor"),
            "argument": f"{_factor_label(item)}：{item.get('explanation')}",
            "strength": _strength_from_impact(int(item.get("impact") or 0)),
        }
        for item in negative[:3]
    ]

    key_disagreement = []
    if bull_case and bear_case:
        key_disagreement.append(
            {
                "topic": strategy.get("name") or strategy.get("id") or "当前策略判断",
                "bull_view": bull_case[0]["argument"],
                "bear_view": bear_case[0]["argument"],
            }
        )

    financial = stock_data.get("financial") or {}
    price = stock_data.get("price")
    falsification = []
    if financial.get("net_profit_yoy") is not None:
        falsification.append(
            {
                "condition": "若后续利润同比继续转负或明显走弱，则当前基本面改善逻辑失效。",
            }
        )
    if price not in (None, "", 0):
        falsification.append(
            {
                "condition": "若价格重新跌回关键趋势下方且量能同步转弱，则当前观察逻辑需要降级。",
            }
        )
    if veto_result.get("warnings"):
        falsification.append(
            {
                "condition": "若当前软风险进一步恶化并升级为红灯，则该标的应停止进入观察池。",
            }
        )

    return {
        "bull_case": bull_case[:3],
        "bear_case": bear_case[:3],
        "key_disagreement": key_disagreement[:2],
        "falsification": falsification[:3],
    }
