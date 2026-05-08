from __future__ import annotations

import re
import unittest
from pathlib import Path


class ComposeHealthcheckTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]
    COMPOSE = ROOT / "docker-compose.yml"

    @classmethod
    def setUpClass(cls) -> None:
        cls.compose_text = cls.COMPOSE.read_text(encoding="utf-8")

    def _service_block(self, service_name: str) -> str:
        marker = f"  {service_name}:"
        lines = self.compose_text.splitlines()
        start = next((index for index, line in enumerate(lines) if line == marker), None)
        self.assertIsNotNone(start, f"{service_name} service is missing")

        end = len(lines)
        for index in range(start + 1, len(lines)):
            line = lines[index]
            if line.startswith("  ") and not line.startswith("    ") and line.strip().endswith(":"):
                end = index
                break
        return "\n".join(lines[start:end])

    def test_core_runtime_services_have_healthchecks(self) -> None:
        for service_name in (
            "postgres",
            "clickhouse",
            "redis",
            "market-service",
            "user-service",
            "analysis-service",
            "data-crawler",
        ):
            with self.subTest(service=service_name):
                self.assertIn("healthcheck:", self._service_block(service_name))

    def test_backend_services_wait_for_healthy_dependencies(self) -> None:
        expected = {
            "market-service": ("postgres", "redis", "clickhouse"),
            "user-service": ("postgres", "redis"),
            "analysis-service": ("postgres", "redis", "clickhouse"),
            "data-crawler": ("postgres", "redis", "clickhouse"),
            "web": ("market-service", "user-service", "analysis-service"),
        }

        for service_name, dependencies in expected.items():
            block = self._service_block(service_name)
            with self.subTest(service=service_name):
                for dependency in dependencies:
                    self.assertRegex(
                        block,
                        rf"(?m)^\s{{6}}{re.escape(dependency)}:\n\s{{8}}condition: service_healthy$",
                    )


if __name__ == "__main__":
    unittest.main()
