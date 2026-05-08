from __future__ import annotations

import importlib
import sys
import unittest
import warnings
from datetime import datetime, timezone
from types import SimpleNamespace

from pydantic.warnings import PydanticDeprecatedSince20
from sqlalchemy.exc import MovedIn20Warning


class SharedDeprecationWarningTests(unittest.TestCase):
    def test_models_import_without_sqlalchemy_movedin20_warning(self) -> None:
        sys.modules.pop("backend.shared.models", None)

        with warnings.catch_warnings():
            warnings.simplefilter("error", MovedIn20Warning)
            importlib.import_module("backend.shared.models")

    def test_schemas_import_without_pydantic_config_warning(self) -> None:
        sys.modules.pop("backend.shared.schemas", None)

        with warnings.catch_warnings():
            warnings.simplefilter("error", PydanticDeprecatedSince20)
            importlib.import_module("backend.shared.schemas")

    def test_response_schema_still_validates_from_attributes(self) -> None:
        schemas = importlib.import_module("backend.shared.schemas")
        updated_at = datetime.now(timezone.utc)
        stock = SimpleNamespace(
            id=1,
            symbol="000001",
            name="Ping An Bank",
            market="SZ",
            sector=None,
            list_date=None,
            is_active=True,
            updated_at=updated_at,
        )

        response = schemas.StockResponse.model_validate(stock)

        self.assertEqual(response.symbol, "000001")
        self.assertEqual(response.updated_at, updated_at)


if __name__ == "__main__":
    unittest.main()
