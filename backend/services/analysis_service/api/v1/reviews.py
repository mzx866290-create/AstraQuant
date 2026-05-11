from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.services.analysis_service.engine.review_tracker import (
    VALID_REVIEW_OFFSETS,
    build_recent_review_summaries,
)

router = APIRouter(tags=["复盘摘要"])


def _parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@router.get("/recent")
async def get_recent_reviews(
    symbols: str = Query(..., min_length=1),
    strategy: str = Query(default="auto", min_length=1),
    offsets: str = Query(default="T+1,T+5,T+20"),
    limit_per_symbol: int = Query(default=1, ge=1, le=5),
):
    symbol_list = _parse_csv(symbols)
    if not symbol_list:
        raise HTTPException(status_code=400, detail="symbols must include at least one symbol")

    offset_list = _parse_csv(offsets)
    invalid_offsets = [offset for offset in offset_list if offset not in VALID_REVIEW_OFFSETS]
    if not offset_list or invalid_offsets:
        allowed = ", ".join(VALID_REVIEW_OFFSETS)
        raise HTTPException(status_code=400, detail=f"offsets only accepts: {allowed}")

    return build_recent_review_summaries(
        symbol_list,
        strategy=strategy.strip() or "auto",
        offsets=tuple(offset_list),
        limit_per_symbol=limit_per_symbol,
    )
