from __future__ import annotations

import re
import unittest
from pathlib import Path


class PrometheusAlertingConfigTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]
    PROMETHEUS_CONFIG = ROOT / "infra/prometheus/prometheus.yml"
    RULES_FILE = ROOT / "infra/prometheus/rules/service-alerts.yml"

    def test_prometheus_loads_alert_rule_files(self) -> None:
        prometheus = self.PROMETHEUS_CONFIG.read_text(encoding="utf-8")
        compose = (self.ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertRegex(prometheus, r"(?m)^rule_files:\s*$")
        self.assertIn("- /etc/prometheus/rules/*.yml", prometheus)
        self.assertIn("./infra/prometheus/rules:/etc/prometheus/rules:ro", compose)

    def test_core_service_alerts_are_defined(self) -> None:
        rules = self.RULES_FILE.read_text(encoding="utf-8")

        for alert_name in (
            "ServiceMetricsTargetDown",
            "PrometheusTargetMissing",
            "ServiceMetricsScrapeFailing",
            "ServiceHttp5xxRateHigh",
            "DataCrawlerSchedulerStopped",
            "DataCrawlerSchedulerError",
            "DataCrawlerTaskFailing",
        ):
            self.assertIn(f"alert: {alert_name}", rules)

        for job_name in ("market-service", "user-service", "analysis-service", "data-crawler"):
            self.assertIn(job_name, rules)

        self.assertRegex(rules, r"expr:\s+up\{job=~")
        self.assertRegex(rules, r"expr:\s+absent\(up\{job=~")
        self.assertRegex(rules, r"expr:\s+scrape_samples_scraped\{job=~")
        self.assertIn("stock_platform_http_requests_total", rules)
        self.assertIn("stock_platform_data_crawler_scheduler_running", rules)
        self.assertIn("stock_platform_data_crawler_scheduler_error", rules)
        self.assertIn("stock_platform_data_crawler_task_last_status", rules)

    def test_service_requirements_include_prometheus_client(self) -> None:
        requirements_files = sorted((self.ROOT / "backend/services").glob("*/requirements.txt"))
        self.assertGreaterEqual(len(requirements_files), 4)

        missing = [
            str(path.relative_to(self.ROOT))
            for path in requirements_files
            if not re.search(r"(?m)^prometheus-client(?:==|>=)", path.read_text(encoding="utf-8"))
        ]

        self.assertEqual([], missing)


if __name__ == "__main__":
    unittest.main()
