from __future__ import annotations

import importlib
import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from backend.shared.auth import get_current_user


SAFE_ENV = {
    "APP_ENV": "development",
    "AUTH_REQUIRED": "true",
    "JWT_SECRET": "test-secret-with-at-least-32-characters",
    "USE_SQLITE": "true",
    "AI_ENCRYPTION_KEY": "test-ai-key",
    "DATA_CRAWLER_ENABLE_SCHEDULER": "false",
}


def _iter_dependencies(dependant):
    for dependency in getattr(dependant, "dependencies", []):
        yield dependency
        yield from _iter_dependencies(dependency)


def _find_current_user_dependencies(app):
    dependencies = []
    for route in app.routes:
        dependant = getattr(route, "dependant", None)
        if dependant is None:
            continue
        for dependency in _iter_dependencies(dependant):
            call = getattr(dependency, "call", None)
            if getattr(call, "__name__", "") == "get_current_user":
                dependencies.append(call)
    return dependencies or [get_current_user]


class _DependencyOverrideMap(dict):
    def __init__(self, initial, current_user_dependencies):
        super().__init__(initial)
        self._current_user_dependencies = tuple(dict.fromkeys(current_user_dependencies))

    def __setitem__(self, key, value):
        if getattr(key, "__name__", "") == "get_current_user":
            for dependency in self._current_user_dependencies:
                super().__setitem__(dependency, value)
            return
        super().__setitem__(key, value)


class AdminReviewStatsApiTests(unittest.TestCase):
    def _import_app(self):
        with patch.dict("os.environ", SAFE_ENV, clear=False):
            auth_module = importlib.import_module("backend.shared.auth")
            importlib.reload(auth_module)
            module = importlib.import_module("backend.services.analysis_service.app.main")
            module = importlib.reload(module)
        current_user_dependencies = _find_current_user_dependencies(module.app)
        module.app.dependency_overrides = _DependencyOverrideMap(
            module.app.dependency_overrides,
            current_user_dependencies,
        )
        global get_current_user
        get_current_user = current_user_dependencies[0]

        # The app authenticates twice per request: once via FastAPI DI
        # (require_admin -> Depends(get_current_user)) which dependency_overrides
        # covers, and once in the api_authentication HTTP middleware which calls
        # get_current_user(...) DIRECTLY by name — DI overrides do not reach it.
        # Mirror the active override into the middleware's call so tests that set
        # dependency_overrides[get_current_user] are honored there too; fall back
        # to the real implementation (which 401s without a token) otherwise.
        real_get_current_user = module.get_current_user

        async def _middleware_get_current_user(credentials=None):
            override = module.app.dependency_overrides.get(get_current_user)
            if override is not None:
                result = override()
                if inspect.isawaitable(result):
                    result = await result
                return result
            result = real_get_current_user(credentials)
            if inspect.isawaitable(result):
                result = await result
            return result

        module.get_current_user = _middleware_get_current_user
        return module.app

    def test_review_scheduler_endpoint_returns_scheduler_status_for_admin(self) -> None:
        app = self._import_app()
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, role="admin", is_active=True)
        expected = {
            "enabled": True,
            "running": False,
            "interval_seconds": 600,
            "last_run_at": None,
            "last_error": None,
            "last_result": {"created": 3},
        }

        with patch(
            "api.v1.admin_stats.review_scheduler.status",
            return_value=expected,
        ):
            response = TestClient(app).get("/api/v1/admin/stats/review-scheduler")
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)

    def test_review_readiness_endpoint_passes_date_and_offsets(self) -> None:
        app = self._import_app()
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, role="admin", is_active=True)
        expected = {
            "status": "pending_reviews",
            "review_date": "2026-05-11",
            "offsets": ["T+1"],
            "tables": {"research_observations": True, "observation_reviews": True},
            "summary": {"observations": 1, "reviews": 0, "pending_reviews": 1, "strategies_with_reviews": 0},
            "latest_snapshot_date": "2026-05-10",
            "latest_review_date": None,
            "pending_reviews": [],
            "review_report_summary": {},
        }

        with patch("api.v1.admin_stats.build_review_readiness", return_value=expected) as readiness:
            response = TestClient(app).get(
                "/api/v1/admin/stats/review-readiness",
                params={"review_date": "2026-05-11", "offsets": "T+1"},
            )
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        self.assertEqual(str(readiness.call_args.kwargs["review_date"]), "2026-05-11")
        self.assertEqual(readiness.call_args.kwargs["offsets"], ("T+1",))

    def test_review_readiness_endpoint_rejects_invalid_offsets(self) -> None:
        app = self._import_app()
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, role="admin", is_active=True)

        response = TestClient(app).get(
            "/api/v1/admin/stats/review-readiness",
            params={"offsets": "T+2"},
        )
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 400)
        self.assertIn("offsets", response.json()["detail"])

    def test_review_report_endpoint_passes_date_filters(self) -> None:
        app = self._import_app()
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, role="admin", is_active=True)
        expected = {
            "status": "ok",
            "summary": {"reviews": 4, "strategies": 2, "avg_return_pct": 1.25},
            "by_strategy": [
                {
                    "strategy_id": "retail_small",
                    "reviews": 4,
                    "positive_reviews": 3,
                    "avg_return_pct": 1.25,
                    "falsification_triggered": 1,
                    "risk_signal_valid": 1,
                    "win_rate": 0.75,
                }
            ],
        }

        with patch(
            "api.v1.admin_stats.build_review_report",
            return_value=expected,
        ) as report:
            response = TestClient(app).get(
                "/api/v1/admin/stats/review-report",
                params={"snapshot_from": "2026-05-01", "snapshot_to": "2026-05-10"},
            )
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        kwargs = report.call_args.kwargs
        self.assertEqual(str(kwargs["snapshot_from"]), "2026-05-01")
        self.assertEqual(str(kwargs["snapshot_to"]), "2026-05-10")

    def test_review_report_endpoint_rejects_invalid_date_range(self) -> None:
        app = self._import_app()
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, role="admin", is_active=True)

        response = TestClient(app).get(
            "/api/v1/admin/stats/review-report",
            params={"snapshot_from": "2026-05-11", "snapshot_to": "2026-05-10"},
        )
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 400)
        self.assertIn("snapshot_from", response.json()["detail"])

    def test_review_factor_report_endpoint_passes_date_filters(self) -> None:
        app = self._import_app()
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, role="admin", is_active=True)
        expected = {
            "status": "ok",
            "summary": {"factors": 1, "reviews": 2},
            "by_factor": [
                {
                    "factor": "valuation",
                    "label": "Valuation",
                    "reviews": 2,
                    "positive_reviews": 1,
                    "win_rate": 0.5,
                    "avg_return_pct": 2.5,
                    "avg_impact": 0.75,
                    "positive_impact_reviews": 1,
                    "negative_impact_reviews": 0,
                    "falsification_triggered": 1,
                    "risk_signal_valid": 1,
                }
            ],
        }

        with patch(
            "api.v1.admin_stats.build_factor_review_report",
            return_value=expected,
        ) as report:
            response = TestClient(app).get(
                "/api/v1/admin/stats/review-factor-report",
                params={"snapshot_from": "2026-05-01", "snapshot_to": "2026-05-10"},
            )
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        kwargs = report.call_args.kwargs
        self.assertEqual(str(kwargs["snapshot_from"]), "2026-05-01")
        self.assertEqual(str(kwargs["snapshot_to"]), "2026-05-10")

    def test_review_factor_report_endpoint_rejects_invalid_date_range(self) -> None:
        app = self._import_app()
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, role="admin", is_active=True)

        response = TestClient(app).get(
            "/api/v1/admin/stats/review-factor-report",
            params={"snapshot_from": "2026-05-11", "snapshot_to": "2026-05-10"},
        )
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 400)
        self.assertIn("snapshot_from", response.json()["detail"])

    def test_review_factor_validation_endpoint_passes_filters(self) -> None:
        app = self._import_app()
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, role="admin", is_active=True)
        expected = {
            "status": "ok",
            "factor": "valuation",
            "summary": {"reviews": 2, "min_reviews": 3, "validation_state": "observed"},
            "by_offset": [],
            "samples": [],
        }

        with patch("api.v1.admin_stats.build_single_factor_validation_report", return_value=expected) as report:
            response = TestClient(app).get(
                "/api/v1/admin/stats/review-factor-validation",
                params={"factor": "valuation", "snapshot_from": "2026-05-01", "snapshot_to": "2026-05-10", "min_reviews": "3"},
            )
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        kwargs = report.call_args.kwargs
        self.assertEqual(kwargs["factor"], "valuation")
        self.assertEqual(kwargs["min_reviews"], 3)
        self.assertEqual(str(kwargs["snapshot_from"]), "2026-05-01")
        self.assertEqual(str(kwargs["snapshot_to"]), "2026-05-10")

    def test_review_factor_validation_endpoint_rejects_invalid_date_range(self) -> None:
        app = self._import_app()
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, role="admin", is_active=True)

        response = TestClient(app).get(
            "/api/v1/admin/stats/review-factor-validation",
            params={"factor": "valuation", "snapshot_from": "2026-05-11", "snapshot_to": "2026-05-10"},
        )
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 400)
        self.assertIn("snapshot_from", response.json()["detail"])

    def test_review_factor_validation_endpoint_rejects_missing_factor(self) -> None:
        app = self._import_app()
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, role="admin", is_active=True)

        response = TestClient(app).get("/api/v1/admin/stats/review-factor-validation")
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 422)

    def test_review_weight_suggestions_endpoint_passes_filters_and_min_reviews(self) -> None:
        app = self._import_app()
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, role="admin", is_active=True)
        expected = {
            "status": "ok",
            "summary": {"suggestions": 1, "eligible_factors": 1, "min_reviews": 5},
            "suggestions": [
                {
                    "factor": "valuation",
                    "label": "Valuation",
                    "action": "increase",
                    "confidence": "medium",
                    "reason": "unit",
                    "metrics": {
                        "reviews": 5,
                        "win_rate": 0.8,
                        "avg_return_pct": 3.0,
                        "avg_impact": 0.7,
                        "falsification_triggered": 0,
                        "risk_signal_valid": 1,
                    },
                }
            ],
        }

        with patch(
            "api.v1.admin_stats.build_weight_adjustment_suggestions",
            return_value=expected,
        ) as suggestions:
            response = TestClient(app).get(
                "/api/v1/admin/stats/review-weight-suggestions",
                params={"min_reviews": "5", "snapshot_from": "2026-05-01", "snapshot_to": "2026-05-10"},
            )
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        kwargs = suggestions.call_args.kwargs
        self.assertEqual(kwargs["min_reviews"], 5)
        self.assertEqual(str(kwargs["snapshot_from"]), "2026-05-01")
        self.assertEqual(str(kwargs["snapshot_to"]), "2026-05-10")

    def test_review_weight_suggestions_endpoint_can_save_audit(self) -> None:
        app = self._import_app()
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, role="admin", is_active=True)
        expected = {
            "status": "ok",
            "summary": {"suggestions": 0, "eligible_factors": 0, "min_reviews": 5},
            "suggestions": [],
        }

        with patch(
            "api.v1.admin_stats.build_weight_adjustment_suggestions",
            return_value=expected,
        ), patch("api.v1.admin_stats.save_weight_suggestion_audit", return_value=77) as save_audit:
            response = TestClient(app).get(
                "/api/v1/admin/stats/review-weight-suggestions",
                params={
                    "min_reviews": "5",
                    "snapshot_from": "2026-05-01",
                    "snapshot_to": "2026-05-10",
                    "save_audit": "true",
                },
            )
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["audit_id"], 77)
        kwargs = save_audit.call_args.kwargs
        self.assertEqual(kwargs["min_reviews"], 5)
        self.assertEqual(str(kwargs["snapshot_from"]), "2026-05-01")
        self.assertEqual(str(kwargs["snapshot_to"]), "2026-05-10")

    def test_review_weight_suggestion_audits_endpoint_lists_recent_records(self) -> None:
        app = self._import_app()
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, role="admin", is_active=True)
        expected = [{"id": 7, "status": "ok", "suggestions": [], "summary": {}}]

        with patch("api.v1.admin_stats.list_weight_suggestion_audits", return_value=expected) as list_audits:
            response = TestClient(app).get(
                "/api/v1/admin/stats/review-weight-suggestion-audits",
                params={"limit": "10"},
            )
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        self.assertEqual(list_audits.call_args.kwargs["limit"], 10)

    def test_review_weight_suggestion_audit_patch_updates_decision(self) -> None:
        app = self._import_app()
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=42, role="admin", is_active=True)
        expected = {"id": 7, "accepted": True, "accepted_by": 42, "notes": "approved"}

        with patch("api.v1.admin_stats.update_weight_suggestion_audit", return_value=expected) as update_audit:
            response = TestClient(app).patch(
                "/api/v1/admin/stats/review-weight-suggestion-audits/7",
                json={"accepted": True, "notes": "approved"},
            )
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        self.assertEqual(update_audit.call_args.args[0], 7)
        self.assertEqual(update_audit.call_args.kwargs["accepted"], True)
        self.assertEqual(update_audit.call_args.kwargs["notes"], "approved")
        self.assertEqual(update_audit.call_args.kwargs["accepted_by"], 42)
        self.assertEqual(update_audit.call_args.kwargs["accepted_provided"], True)

    def test_review_weight_suggestion_audit_patch_can_clear_decision(self) -> None:
        app = self._import_app()
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=42, role="admin", is_active=True)
        expected = {"id": 7, "accepted": None, "accepted_by": None, "notes": "reset"}

        with patch("api.v1.admin_stats.update_weight_suggestion_audit", return_value=expected) as update_audit:
            response = TestClient(app).patch(
                "/api/v1/admin/stats/review-weight-suggestion-audits/7",
                json={"accepted": None, "notes": "reset"},
            )
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        self.assertIsNone(update_audit.call_args.kwargs["accepted"])
        self.assertEqual(update_audit.call_args.kwargs["accepted_provided"], True)

    def test_review_weight_suggestion_audit_patch_returns_404_when_missing(self) -> None:
        app = self._import_app()
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=42, role="admin", is_active=True)

        with patch("api.v1.admin_stats.update_weight_suggestion_audit", return_value=None):
            response = TestClient(app).patch(
                "/api/v1/admin/stats/review-weight-suggestion-audits/404",
                json={"notes": "missing"},
            )
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 404)

    def test_review_weight_suggestion_strategy_patch_endpoint_passes_params(self) -> None:
        app = self._import_app()
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=42, role="admin", is_active=True)
        expected = {
            "status": "ok",
            "audit_id": 7,
            "strategy_id": "value_quality",
            "step": 0.02,
            "max_delta": 0.05,
            "before": {"valuation": 0.5},
            "after": {"valuation": 1.0},
            "delta": {"valuation": 0.5},
            "items": [],
        }

        with patch("api.v1.admin_stats.build_weight_strategy_patch_preview", return_value=expected) as preview:
            response = TestClient(app).get(
                "/api/v1/admin/stats/review-weight-suggestion-audits/7/strategy-patch",
                params={"strategy_id": "value_quality", "step": "0.02", "max_delta": "0.05"},
            )
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        self.assertEqual(preview.call_args.args[0], 7)
        self.assertEqual(preview.call_args.kwargs["strategy_id"], "value_quality")
        self.assertEqual(preview.call_args.kwargs["step"], 0.02)
        self.assertEqual(preview.call_args.kwargs["max_delta"], 0.05)

    def test_strategy_weight_patch_proposal_endpoint_creates_pending_record(self) -> None:
        app = self._import_app()
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=42, role="admin", is_active=True)
        expected = {"id": 9, "audit_id": 7, "strategy_id": "retail_small", "status": "pending"}

        with patch("api.v1.admin_stats.create_strategy_weight_patch_proposal", return_value=expected) as create:
            response = TestClient(app).post(
                "/api/v1/admin/stats/review-weight-suggestion-audits/7/strategy-patch-proposals",
                json={"strategy_id": "retail_small", "step": 0.02, "max_delta": 0.05, "notes": "candidate"},
            )
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        self.assertEqual(create.call_args.args[0], 7)
        self.assertEqual(create.call_args.kwargs["created_by"], 42)
        self.assertEqual(create.call_args.kwargs["notes"], "candidate")

    def test_strategy_weight_patch_proposals_endpoint_lists_records(self) -> None:
        app = self._import_app()
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=42, role="admin", is_active=True)
        expected = [{"id": 9, "status": "pending"}]

        with patch("api.v1.admin_stats.list_strategy_weight_patch_proposals", return_value=expected) as list_proposals:
            response = TestClient(app).get(
                "/api/v1/admin/stats/strategy-weight-patch-proposals",
                params={"limit": "10", "status": "pending"},
            )
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        self.assertEqual(list_proposals.call_args.kwargs["limit"], 10)
        self.assertEqual(list_proposals.call_args.kwargs["status"], "pending")

    def test_strategy_weight_patch_proposal_patch_updates_status(self) -> None:
        app = self._import_app()
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=42, role="admin", is_active=True)
        expected = {"id": 9, "status": "approved", "decided_by": 42}

        with patch("api.v1.admin_stats.decide_strategy_weight_patch_proposal", return_value=expected) as decide:
            response = TestClient(app).patch(
                "/api/v1/admin/stats/strategy-weight-patch-proposals/9",
                json={"status": "approved", "notes": "ok"},
            )
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        self.assertEqual(decide.call_args.args[0], 9)
        self.assertEqual(decide.call_args.kwargs["status"], "approved")
        self.assertEqual(decide.call_args.kwargs["decided_by"], 42)

    def test_strategy_weight_patch_proposal_apply_endpoint_applies_approved_record(self) -> None:
        app = self._import_app()
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=42, role="admin", is_active=True)
        expected = {"id": 9, "status": "applied", "applied_by": 42}

        with patch("api.v1.admin_stats.apply_strategy_weight_patch_proposal", return_value=expected) as apply_patch:
            response = TestClient(app).post(
                "/api/v1/admin/stats/strategy-weight-patch-proposals/9/apply",
                json={"notes": "apply"},
            )
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        self.assertEqual(apply_patch.call_args.args[0], 9)
        self.assertEqual(apply_patch.call_args.kwargs["applied_by"], 42)
        self.assertEqual(apply_patch.call_args.kwargs["notes"], "apply")

    def test_strategy_weight_patch_proposal_apply_endpoint_rejects_not_ready_record(self) -> None:
        app = self._import_app()
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=42, role="admin", is_active=True)
        expected = {"id": 9, "status": "pending"}

        with patch("api.v1.admin_stats.apply_strategy_weight_patch_proposal", return_value=expected):
            response = TestClient(app).post("/api/v1/admin/stats/strategy-weight-patch-proposals/9/apply")
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], expected)

    def test_strategy_weight_patch_proposal_impact_preview_endpoint_passes_params(self) -> None:
        app = self._import_app()
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=42, role="admin", is_active=True)
        expected = {"status": "ok", "proposal_id": 9, "items": []}

        with patch("api.v1.admin_stats.preview_strategy_weight_proposal_impact", AsyncMock(return_value=expected)) as preview:
            response = TestClient(app).get(
                "/api/v1/admin/stats/strategy-weight-patch-proposals/9/impact-preview",
                params={"market": "SZ", "limit": "12", "candidate_limit": "40", "concurrency": "4"},
            )
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        self.assertEqual(preview.call_args.args[0], 9)
        self.assertEqual(preview.call_args.kwargs["market"], "SZ")
        self.assertEqual(preview.call_args.kwargs["limit"], 12)
        self.assertEqual(preview.call_args.kwargs["candidate_limit"], 40)
        self.assertEqual(preview.call_args.kwargs["concurrency"], 4)

    def test_strategy_weight_patch_proposal_impact_preview_endpoint_returns_404_when_missing(self) -> None:
        app = self._import_app()
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=42, role="admin", is_active=True)
        expected = {"status": "proposal_not_found", "proposal_id": 9, "items": []}

        with patch("api.v1.admin_stats.preview_strategy_weight_proposal_impact", AsyncMock(return_value=expected)):
            response = TestClient(app).get("/api/v1/admin/stats/strategy-weight-patch-proposals/9/impact-preview")
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 404)

    def test_strategy_weight_versions_endpoint_lists_records(self) -> None:
        app = self._import_app()
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=42, role="admin", is_active=True)
        expected = [{"id": 11, "strategy_id": "retail_small", "version": 1}]

        with patch("api.v1.admin_stats.list_strategy_weight_versions", return_value=expected) as list_versions:
            response = TestClient(app).get(
                "/api/v1/admin/stats/strategy-weight-versions",
                params={"strategy_id": "retail_small", "limit": "10"},
            )
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        self.assertEqual(list_versions.call_args.kwargs["strategy_id"], "retail_small")
        self.assertEqual(list_versions.call_args.kwargs["limit"], 10)

    def test_strategy_weight_version_rollback_endpoint_rolls_back_record(self) -> None:
        app = self._import_app()
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=42, role="admin", is_active=True)
        expected = {"id": 11, "rolled_back_by": 42, "rolled_back_at": "2026-05-10T12:00:00"}

        with patch("api.v1.admin_stats.rollback_strategy_weight_version", return_value=expected) as rollback:
            response = TestClient(app).post(
                "/api/v1/admin/stats/strategy-weight-versions/11/rollback",
                json={"notes": "rollback"},
            )
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        self.assertEqual(rollback.call_args.args[0], 11)
        self.assertEqual(rollback.call_args.kwargs["rolled_back_by"], 42)
        self.assertEqual(rollback.call_args.kwargs["notes"], "rollback")

    def test_strategy_weight_version_rollback_endpoint_rejects_failed_rollback(self) -> None:
        app = self._import_app()
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=42, role="admin", is_active=True)
        expected = {"id": 11, "rollback_error": "strategy config not found"}

        with patch("api.v1.admin_stats.rollback_strategy_weight_version", return_value=expected):
            response = TestClient(app).post("/api/v1/admin/stats/strategy-weight-versions/11/rollback")
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], expected)

    def test_review_weight_suggestions_endpoint_rejects_invalid_date_range(self) -> None:
        app = self._import_app()
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, role="admin", is_active=True)

        response = TestClient(app).get(
            "/api/v1/admin/stats/review-weight-suggestions",
            params={"snapshot_from": "2026-05-11", "snapshot_to": "2026-05-10"},
        )
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 400)
        self.assertIn("snapshot_from", response.json()["detail"])

    def test_review_weight_suggestions_endpoint_rejects_invalid_min_reviews(self) -> None:
        app = self._import_app()
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, role="admin", is_active=True)

        response = TestClient(app).get(
            "/api/v1/admin/stats/review-weight-suggestions",
            params={"min_reviews": "0"},
        )
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 422)

    def test_review_run_endpoint_triggers_scheduler_once(self) -> None:
        app = self._import_app()
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, role="admin", is_active=True)
        expected = {
            "run_pending_reviews": {"review_date": "2026-05-10", "processed": 2, "created": 1, "status": "ok"},
            "review_report": {"status": "ok", "summary": {"reviews": 8}, "by_strategy": []},
        }

        with patch(
            "api.v1.admin_stats.review_scheduler.run_once",
            AsyncMock(return_value=expected),
        ) as run_once:
            response = TestClient(app).post(
                "/api/v1/admin/stats/review-scheduler/run-once",
                params={"review_date": "2026-05-10"},
            )
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        self.assertEqual(str(run_once.call_args.kwargs["review_date"]), "2026-05-10")

    def test_review_run_endpoint_rejects_invalid_date(self) -> None:
        app = self._import_app()
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, role="admin", is_active=True)

        response = TestClient(app).post(
            "/api/v1/admin/stats/review-scheduler/run-once",
            params={"review_date": "bad-date"},
        )
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
