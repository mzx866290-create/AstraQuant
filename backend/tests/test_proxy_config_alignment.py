from __future__ import annotations

import unittest
from pathlib import Path


class ProxyConfigAlignmentTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    def test_vite_and_nginx_align_on_admin_and_analysis_proxies(self) -> None:
        vite = (self.ROOT / "frontend/web/vite.config.ts").read_text(encoding="utf-8")
        nginx = (self.ROOT / "frontend/web/nginx.conf").read_text(encoding="utf-8")

        self.assertIn("'/api/v1/analysis'", vite)
        self.assertIn("target: 'http://localhost:8003'", vite)
        self.assertIn("location /api/v1/analysis", nginx)
        self.assertIn("proxy_pass http://analysis-service:8000;", nginx)

        self.assertIn("'/api/v1/admin'", vite)
        self.assertIn("location /api/v1/admin", nginx)

    def test_market_fallback_proxy_is_scoped_to_api_v1_only(self) -> None:
        vite = (self.ROOT / "frontend/web/vite.config.ts").read_text(encoding="utf-8")
        nginx = (self.ROOT / "frontend/web/nginx.conf").read_text(encoding="utf-8")

        self.assertIn("'/api/v1': {", vite)
        self.assertIn("location /api/v1/ {", nginx)
        self.assertNotIn("location /api/ {", nginx)

    def test_vite_dev_server_does_not_default_to_public_host(self) -> None:
        vite = (self.ROOT / "frontend/web/vite.config.ts").read_text(encoding="utf-8")

        self.assertIn("host: process.env.VITE_DEV_HOST || '127.0.0.1'", vite)
        self.assertIn("strictPort: true", vite)
        self.assertNotIn("host: '0.0.0.0'", vite)
        self.assertNotIn("'yhang.cc.cd'", vite)


if __name__ == "__main__":
    unittest.main()
