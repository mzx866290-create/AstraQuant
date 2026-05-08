from __future__ import annotations

import unittest
from pathlib import Path


class ProductMvpDocsTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    def test_product_mvp_doc_captures_trust_boundaries(self) -> None:
        doc = (self.ROOT / "docs/product-mvp.md").read_text(encoding="utf-8")

        for phrase in (
            "不是荐股工具",
            "数据可信等级",
            "调试数据",
            "AI 输出边界",
            "docker compose config",
            "fallback 候选不能被当成真实推荐",
        ):
            self.assertIn(phrase, doc)

    def test_readme_links_to_product_mvp_doc(self) -> None:
        readme = (self.ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("docs/product-mvp.md", readme)


if __name__ == "__main__":
    unittest.main()
