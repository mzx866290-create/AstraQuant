from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fastapi import Response

from backend.services.data_crawler.pipeline import crawl_status
from backend.shared import audit, observability


class _FakeMetric:
    def __init__(self, name: str, _description: str, _labels=()) -> None:
        self.name = name
        self.operations: list[tuple[str, dict, float | None]] = []
        self.current_labels: dict = {}

    def labels(self, **labels):
        self.current_labels = labels
        return self

    def inc(self) -> None:
        self.operations.append(("inc", dict(self.current_labels), None))

    def dec(self) -> None:
        self.operations.append(("dec", dict(self.current_labels), None))

    def set(self, value: float) -> None:
        self.operations.append(("set", dict(self.current_labels), value))

    def observe(self, value: float) -> None:
        self.operations.append(("observe", dict(self.current_labels), value))


class _FakeApp:
    def __init__(self) -> None:
        self.title = "Unit API"
        self.state = SimpleNamespace(metrics_installed=False)
        self.routes = {}
        self.middlewares = []

    def get(self, path: str, **_kwargs):
        def decorator(func):
            self.routes[path] = func
            return func

        return decorator

    def middleware(self, _kind: str):
        def decorator(func):
            self.middlewares.append(func)
            return func

        return decorator


def _prometheus_module() -> ModuleType:
    module = ModuleType("prometheus_client")
    module.CONTENT_TYPE_LATEST = "text/plain; version=0.0.4"
    module.Counter = _FakeMetric
    module.Gauge = _FakeMetric
    module.Histogram = _FakeMetric
    module.generate_latest = lambda: b"unit-metrics"
    return module


class ObservabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self._metric_globals = {
            "HTTP_REQUESTS_TOTAL": observability.HTTP_REQUESTS_TOTAL,
            "HTTP_REQUEST_DURATION_SECONDS": observability.HTTP_REQUEST_DURATION_SECONDS,
            "HTTP_REQUESTS_IN_PROGRESS": observability.HTTP_REQUESTS_IN_PROGRESS,
            "SERVICE_INFO": observability.SERVICE_INFO,
        }
        observability.HTTP_REQUESTS_TOTAL = None
        observability.HTTP_REQUEST_DURATION_SECONDS = None
        observability.HTTP_REQUESTS_IN_PROGRESS = None
        observability.SERVICE_INFO = None

    def tearDown(self) -> None:
        for name, value in self._metric_globals.items():
            setattr(observability, name, value)

    def test_metric_path_prefers_route_template_and_falls_back_to_url_path(self) -> None:
        routed = SimpleNamespace(
            scope={"route": SimpleNamespace(path="/stocks/{symbol}")},
            url=SimpleNamespace(path="/stocks/600519"),
        )
        unrouted = SimpleNamespace(scope={}, url=SimpleNamespace(path="/health"))

        self.assertEqual(observability._metric_path(routed), "/stocks/{symbol}")
        self.assertEqual(observability._metric_path(unrouted), "/health")

    def test_install_metrics_registers_endpoint_and_records_middleware_labels(self) -> None:
        app = _FakeApp()

        with patch.dict("sys.modules", {"prometheus_client": _prometheus_module()}):
            observability.install_metrics(app, service_name="unit-service")

        self.assertTrue(app.state.metrics_installed)
        self.assertIn("/metrics", app.routes)
        self.assertEqual(len(app.middlewares), 1)
        response = asyncio.run(app.routes["/metrics"]())
        self.assertEqual(response.body, b"unit-metrics")

        request = SimpleNamespace(
            url=SimpleNamespace(path="/stocks/600519"),
            method="GET",
            scope={"route": SimpleNamespace(path="/stocks/{symbol}")},
        )

        async def call_next(_request):
            return SimpleNamespace(status_code=204)

        result = asyncio.run(app.middlewares[0](request, call_next))

        self.assertEqual(result.status_code, 204)
        total_ops = observability.HTTP_REQUESTS_TOTAL.operations
        duration_ops = observability.HTTP_REQUEST_DURATION_SECONDS.operations
        inflight_ops = observability.HTTP_REQUESTS_IN_PROGRESS.operations
        self.assertEqual(total_ops[-1][1]["service"], "unit-service")
        self.assertEqual(total_ops[-1][1]["path"], "/stocks/{symbol}")
        self.assertEqual(total_ops[-1][1]["status_code"], "204")
        self.assertEqual(duration_ops[-1][0], "observe")
        self.assertEqual([item[0] for item in inflight_ops[-2:]], ["inc", "dec"])

        route_count = len(app.routes)
        middleware_count = len(app.middlewares)
        observability.install_metrics(app, service_name="unit-service")
        self.assertEqual(len(app.routes), route_count)
        self.assertEqual(len(app.middlewares), middleware_count)

    def test_install_metrics_disables_cleanly_when_prometheus_import_fails(self) -> None:
        app = _FakeApp()

        def fail_import(name, *args, **kwargs):
            if name == "prometheus_client":
                raise ImportError("missing")
            return __import__(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fail_import):
            observability.install_metrics(app, service_name="unit-service")

        self.assertFalse(app.state.metrics_installed)
        self.assertEqual(app.routes, {})

    def test_database_redis_clickhouse_checks_return_explicit_health_status(self) -> None:
        class _Conn:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, statement) -> None:
                self.statement = statement

        ok_database = SimpleNamespace(engine=SimpleNamespace(connect=lambda: _Conn()))
        broken_database = SimpleNamespace(engine=SimpleNamespace(connect=Mock(side_effect=RuntimeError("db down"))))
        ok_cache = SimpleNamespace(redis_client=object())
        no_cache = SimpleNamespace(redis_client=None)

        with patch.dict("sys.modules", {"backend.shared.database": ok_database}):
            self.assertEqual(observability.database_check()["status"], "ok")
        with patch.dict("sys.modules", {"backend.shared.database": broken_database}):
            failed = observability.database_check()
        self.assertEqual(failed["status"], "error")
        self.assertIn("db down", failed["error"])

        with patch.dict("sys.modules", {"backend.shared.cache": ok_cache}):
            self.assertEqual(observability.redis_check(required=True)["status"], "ok")
        with patch.dict("sys.modules", {"backend.shared.cache": no_cache}):
            degraded = observability.redis_check(required=False)
        self.assertEqual(degraded["status"], "degraded")
        self.assertFalse(degraded["required"])

        class _HttpResponse:
            status = 204

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        with patch("urllib.request.urlopen", return_value=_HttpResponse()) as urlopen:
            self.assertEqual(observability.clickhouse_check(required=True)["status"], "ok")
        self.assertIn("/ping", urlopen.call_args.args[0])

        with patch("urllib.request.urlopen", side_effect=TimeoutError("timeout")):
            clickhouse = observability.clickhouse_check(required=False)
        self.assertEqual(clickhouse["status"], "degraded")
        self.assertIn("timeout", clickhouse["error"])

    def test_readiness_response_marks_required_failures_as_503(self) -> None:
        response = Response()

        payload = observability.readiness_response(
            "unit-service",
            response,
            [
                lambda: {"name": "db", "status": "ok", "required": True},
                lambda: {"name": "redis", "status": "degraded", "required": False},
                lambda: {"name": "clickhouse", "status": "error", "required": True},
            ],
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(payload["status"], "not_ready")
        self.assertEqual(payload["service"], "unit-service")
        self.assertEqual(len(payload["checks"]), 3)


class AuditTests(unittest.TestCase):
    def test_client_ip_prefers_forwarded_header_and_user_agent_is_truncated(self) -> None:
        request = SimpleNamespace(
            headers={
                "x-forwarded-for": " 203.0.113.5, 198.51.100.2",
                "user-agent": "A" * 1200,
            },
            client=SimpleNamespace(host="127.0.0.1"),
        )

        self.assertEqual(audit.client_ip(request), "203.0.113.5")
        self.assertEqual(len(audit.user_agent(request)), 1000)
        self.assertIsNone(audit.client_ip(None))
        self.assertIsNone(audit.user_agent(None))

    def test_audit_log_adds_activity_row_without_committing_transaction(self) -> None:
        db = SimpleNamespace(add=Mock())
        request = SimpleNamespace(headers={"user-agent": "unit-agent"}, client=SimpleNamespace(host="10.0.0.7"))

        audit.audit_log(
            db,
            action="admin.changed.very.long.action.name.that.should.be.truncated",
            actor=SimpleNamespace(id=42),
            request=request,
            target="T" * 150,
        )

        row = db.add.call_args.args[0]
        self.assertEqual(row.user_id, 42)
        self.assertEqual(row.action, "admin.changed.very.long.action.name.that.should.be"[:50])
        self.assertEqual(row.target, "T" * 100)
        self.assertEqual(row.ip_address, "10.0.0.7")
        self.assertEqual(row.user_agent, "unit-agent")
        self.assertFalse(hasattr(db, "commit"))

    def test_audit_log_skips_anonymous_and_swallows_write_errors(self) -> None:
        db = SimpleNamespace(add=Mock(side_effect=RuntimeError("db down")))

        audit.audit_log(db, action="anonymous", request=None)
        db.add.assert_not_called()

        audit.audit_log(db, action="write-error", user_id=7, target="unit")
        db.add.assert_called_once()


class CrawlStatusTests(unittest.TestCase):
    def test_count_status_and_symbol_normalization_are_deterministic(self) -> None:
        self.assertEqual(crawl_status.normalize_symbol("600519.SH"), "600519")
        self.assertEqual(crawl_status.normalize_symbol(None), "")
        self.assertEqual(crawl_status.crawl_status_for_counts(0, 0), "empty")
        self.assertEqual(crawl_status.crawl_status_for_counts(5, 0), "no_saved")
        self.assertEqual(crawl_status.crawl_status_for_counts(5, 3), "partial")
        self.assertEqual(crawl_status.crawl_status_for_counts(5, 5), "success")

    def test_record_crawl_status_updates_existing_row_and_truncates_error_message(self) -> None:
        existing = SimpleNamespace(stock_symbol="600519", data_type="daily_kline")
        db = _FakeCrawlStatusSession(existing)
        started = datetime(2026, 5, 7, 10, 0, tzinfo=timezone.utc)
        finished = datetime(2026, 5, 7, 10, 1, tzinfo=timezone.utc)

        with patch.object(crawl_status, "now_utc", return_value=finished):
            row = crawl_status.record_crawl_status(
                db,
                "600519.SH",
                "daily_kline",
                "error",
                started_at=started,
                source="unit-source",
                fetched=9,
                saved=2,
                error_message="x" * 3000,
            )

        self.assertIs(row, existing)
        self.assertEqual(db.added, [])
        self.assertEqual(db.commits, 1)
        self.assertEqual(row.stock_symbol, "600519")
        self.assertEqual(row.data_type, "daily_kline")
        self.assertEqual(row.status, "error")
        self.assertEqual(row.source, "unit-source")
        self.assertEqual(row.fetched_count, 9)
        self.assertEqual(row.saved_count, 2)
        self.assertEqual(len(row.error_message), 2000)
        self.assertEqual(row.started_at, started)
        self.assertEqual(row.finished_at, finished)

    def test_record_crawl_status_creates_row_and_payload_serializes_datetimes(self) -> None:
        db = _FakeCrawlStatusSession(None)
        timestamp = datetime(2026, 5, 7, 11, 0, tzinfo=timezone.utc)

        with patch.object(crawl_status, "now_utc", return_value=timestamp):
            row = crawl_status.record_crawl_status(db, "000001.SZ", "realtime", "success", saved=1)

        self.assertEqual(db.added, [row])
        self.assertEqual(row.stock_symbol, "000001")
        self.assertEqual(row.started_at, timestamp)
        self.assertEqual(row.finished_at, timestamp)

        payload = crawl_status.crawl_status_payload(row)
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["saved"], 1)
        self.assertEqual(payload["started_at"], "2026-05-07T11:00:00+00:00")
        self.assertEqual(payload["finished_at"], "2026-05-07T11:00:00+00:00")


class _FakeCrawlStatusQuery:
    def __init__(self, row) -> None:
        self.row = row

    def filter(self, *_clauses):
        return self

    def first(self):
        return self.row


class _FakeCrawlStatusSession:
    def __init__(self, row) -> None:
        self.row = row
        self.added = []
        self.commits = 0

    def query(self, _model):
        return _FakeCrawlStatusQuery(self.row)

    def add(self, row) -> None:
        self.added.append(row)

    def commit(self) -> None:
        self.commits += 1


if __name__ == "__main__":
    unittest.main()
