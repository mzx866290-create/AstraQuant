from __future__ import annotations

from backend.services.analysis_service.engine.data_quality import DataQualityBuilder, build_readiness


class ContextBuilder:
    """Attach readiness and quality metadata to collected stock data."""

    def enrich(self, stock_data: dict, models_count: int, quota_ready: bool = True, quota_message: str = "") -> dict:
        enriched = dict(stock_data)
        enriched["data_quality"] = DataQualityBuilder.from_stock_data(enriched)
        enriched["readiness"] = build_readiness(enriched, models_count, quota_ready, quota_message)
        return enriched


context_builder = ContextBuilder()
