"""Stock master data synchronization helpers."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable


@dataclass(frozen=True)
class StockMasterSyncResult:
    fetched: int
    inserted: int
    updated: int
    skipped: int
    deactivated: int

    @property
    def saved(self) -> int:
        return self.inserted + self.updated

    def as_dict(self) -> dict:
        return {
            "fetched": self.fetched,
            "inserted": self.inserted,
            "updated": self.updated,
            "skipped": self.skipped,
            "deactivated": self.deactivated,
            "saved": self.saved,
        }


def _stock_code(symbol: str | None) -> str:
    text = str(symbol or "").strip().upper()
    base = text.split(".", 1)[0]
    digits = "".join(ch for ch in base if ch.isdigit())
    return digits[:6]


def _normalize_market(code: str, market: str | None) -> str:
    text = str(market or "").strip().upper()
    if text in {"SH", "SZ", "BJ"}:
        return text
    if code.startswith(("6", "9")):
        return "SH"
    if code.startswith(("0", "1", "2", "3")):
        return "SZ"
    if code.startswith(("4", "8")):
        return "BJ"
    return "SZ"


def _parse_list_date(value) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def normalize_stock_master_row(row: dict) -> dict | None:
    code = _stock_code(row.get("symbol") or row.get("code"))
    if len(code) != 6:
        return None
    name = str(row.get("name") or "").strip()
    if not name or name in {"-", "None"}:
        return None
    if "退" in name or name.startswith(("*ST", "ST")):
        return None
    market = _normalize_market(code, row.get("market"))
    if market not in {"SH", "SZ", "BJ"}:
        return None
    return {
        "symbol": f"{code}.{market}",
        "name": name,
        "market": market,
        "sector": str(row.get("sector") or "").strip() or None,
        "list_date": _parse_list_date(row.get("list_date")),
        "is_active": True,
    }


class StockMasterETL:
    """Upsert stock master rows while preserving existing foreign keys."""

    def save(self, db, rows: Iterable[dict], deactivate_missing: bool = False) -> StockMasterSyncResult:
        from backend.shared.models import Stock

        raw_rows = list(rows)
        normalized = []
        seen_codes: set[str] = set()
        skipped = 0
        for raw in raw_rows:
            row = normalize_stock_master_row(raw)
            if row is None or row["symbol"] in seen_codes:
                skipped += 1
                continue
            normalized.append(row)
            seen_codes.add(row["symbol"])

        existing_rows = db.query(Stock).all()
        by_code: dict[str, Stock] = {}
        for stock in existing_rows:
            code = _stock_code(stock.symbol)
            if code and code not in by_code:
                by_code[code] = stock

        inserted = 0
        updated = 0
        now = datetime.now(timezone.utc)
        for row in normalized:
            code = _stock_code(row["symbol"])
            stock = by_code.get(code)
            if stock is None:
                db.add(Stock(**row, updated_at=now))
                inserted += 1
                continue
            changed = False
            if stock.symbol != row["symbol"]:
                stock.symbol = row["symbol"]
                changed = True
            for field in ("name", "market", "sector", "list_date", "is_active"):
                value = row[field]
                if getattr(stock, field) != value:
                    setattr(stock, field, value)
                    changed = True
            if changed:
                stock.updated_at = now
                updated += 1

        deactivated = 0
        if deactivate_missing and seen_codes:
            for stock in existing_rows:
                code = _stock_code(stock.symbol)
                if code and code not in seen_codes and stock.is_active:
                    stock.is_active = False
                    stock.updated_at = now
                    deactivated += 1

        db.commit()
        return StockMasterSyncResult(
            fetched=len(raw_rows),
            inserted=inserted,
            updated=updated,
            skipped=skipped,
            deactivated=deactivated,
        )
