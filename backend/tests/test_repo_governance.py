from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


class RepoGovernanceTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    def test_gitignore_blocks_runtime_artifacts_and_production_env(self) -> None:
        gitignore = (self.ROOT / ".gitignore").read_text(encoding="utf-8")

        for pattern in (
            ".env",
            ".env.production",
            "*.log",
            "*.out.log",
            "*.err.log",
            "*.db",
            "venv/",
            "__pycache__/",
            "node_modules/",
            "frontend/web/dist/",
        ):
            self.assertIn(pattern, gitignore)

    def test_production_env_uses_template_not_committed_secret_file(self) -> None:
        template = (self.ROOT / ".env.production.example").read_text(encoding="utf-8")

        self.assertIn("APP_ENV=production", template)
        self.assertIn("AUTH_REQUIRED=true", template)
        self.assertIn("USE_SQLITE=false", template)
        self.assertIn("DB_PASS=<set-by-secret-manager>", template)
        self.assertIn("JWT_SECRET=<32-plus-character-random-secret>", template)
        self.assertIn("AI_ENCRYPTION_KEY=<fernet-key-from-cryptography>", template)
        self.assertNotIn("changeme", template)
        self.assertNotIn("admin123", template)

    def test_readme_and_makefile_expose_only_official_start_entries(self) -> None:
        readme = (self.ROOT / "README.md").read_text(encoding="utf-8")
        makefile = (self.ROOT / "Makefile").read_text(encoding="utf-8")

        self.assertIn("python scripts/start_local.py", readme)
        self.assertIn("docker compose up -d", readme)
        self.assertIn("只作为兼容入口保留", readme)

        for target in ("dev", "stack", "test", "lint", "smoke", "verify"):
            self.assertRegex(makefile, rf"(?m)^{target}:")

        self.assertIn("$(PYTHON) scripts/start_local.py", makefile)
        self.assertIn("$(COMPOSE) up -d", makefile)
        self.assertIn("$(NPM) run lint", makefile)
        self.assertIn("$(NPM) run type-check", makefile)
        self.assertIn("$(NPM) run smoke:frontend", makefile)
        self.assertIn("secret-hygiene", makefile)
        self.assertIn("$(PYTHON) scripts/verify_secret_hygiene.py", makefile)
        self.assertIn("make secret-hygiene", readme)
        self.assertIn("python scripts/verify_secret_hygiene.py", readme)

    def test_makefile_and_readme_document_safe_runtime_cleanup_path(self) -> None:
        readme = (self.ROOT / "README.md").read_text(encoding="utf-8")
        makefile = (self.ROOT / "Makefile").read_text(encoding="utf-8")
        cleanup_script = "scripts/cleanup_runtime_artifacts.py"

        for target in ("clean-runtime", "clean-runtime-apply"):
            with self.subTest(target=target):
                self.assertRegex(makefile, rf"(?m)^{target}:")

        self.assertIn(f"$(PYTHON) {cleanup_script}", makefile)
        self.assertIn(f"$(PYTHON) {cleanup_script} --apply", makefile)
        self.assertIn(cleanup_script, readme)
        self.assertIn("dry-run", readme)
        self.assertIn("--apply", readme)
        self.assertIn("make clean-runtime", readme)
        self.assertIn("make clean-runtime-apply", readme)
        self.assertLess(
            readme.index("python scripts/cleanup_runtime_artifacts.py"),
            readme.index("python scripts/cleanup_runtime_artifacts.py --apply"),
        )

    def test_legacy_root_start_scripts_are_compatibility_wrappers(self) -> None:
        legacy_dir = self.ROOT / "scripts" / "legacy"
        self.assertTrue((legacy_dir / "README.md").exists())
        self.assertTrue((legacy_dir / "compat.py").exists())

        python_wrappers = (
            "run_project.py",
            "run_simple_api.py",
            "start_all_sqlite.py",
            "start_market.py",
            "start_simple.py",
            "start_sqlite.py",
            "start_user.py",
        )
        for wrapper in python_wrappers:
            with self.subTest(wrapper=wrapper):
                source = (self.ROOT / wrapper).read_text(encoding="utf-8")
                self.assertLessEqual(len(source.splitlines()), 8)
                self.assertIn("scripts.legacy.compat", source)
                self.assertNotIn("uvicorn.run", source)
                self.assertNotIn("changeme", source)

        bat = (self.ROOT / "start_services.bat").read_text(encoding="utf-8")
        self.assertIn("legacy compatibility wrapper", bat)
        self.assertIn("docker compose up -d", bat)

    def test_frontend_lint_is_installed_and_non_mutating_by_default(self) -> None:
        package_json = json.loads((self.ROOT / "frontend/web/package.json").read_text(encoding="utf-8"))
        scripts = package_json["scripts"]
        dev_dependencies = package_json["devDependencies"]

        self.assertEqual(scripts["lint"], "eslint .")
        self.assertIn("--fix", scripts["lint:fix"])
        self.assertNotIn("--fix", scripts["lint"])
        self.assertEqual(scripts["test:data-quality"], "node scripts/data-quality.mjs")

        for dependency in ("eslint", "@eslint/js", "eslint-plugin-vue", "typescript-eslint"):
            self.assertIn(dependency, dev_dependencies)

        self.assertTrue((self.ROOT / "frontend/web/eslint.config.js").exists())
        self.assertTrue((self.ROOT / "frontend/web/scripts/data-quality.mjs").exists())

    def test_ci_runs_dependencies_before_tests_and_includes_frontend_smoke(self) -> None:
        ci = (self.ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

        expected_steps = (
            "Ops drill readiness preflight",
            "Secret hygiene gate",
            "Install backend dependencies",
            "Install frontend dependencies",
            "Compile backend",
            "Backend unit tests",
            "Backend smoke checks",
            "Lint frontend",
            "Type-check frontend",
            "Frontend data quality contract",
            "Build frontend",
            "Install Playwright browser",
            "Frontend smoke checks",
        )
        for step in expected_steps:
            self.assertIn(f"name: {step}", ci)

        self.assertIn('node-version: "20.19.0"', ci)
        self.assertIn("python scripts/ops/verify_ops_drill_readiness.py", ci)
        self.assertIn("python scripts/verify_secret_hygiene.py", ci)
        self.assertIn("npm run test:data-quality", ci)
        self.assertLess(ci.index("name: Ops drill readiness preflight"), ci.index("name: Compile backend"))
        self.assertLess(ci.index("name: Secret hygiene gate"), ci.index("name: Compile backend"))
        self.assertLess(ci.index("name: Ops drill readiness preflight"), ci.index("name: Backend unit tests"))
        self.assertLess(ci.index("name: Install backend dependencies"), ci.index("name: Backend unit tests"))
        self.assertLess(ci.index("name: Install frontend dependencies"), ci.index("name: Lint frontend"))
        self.assertLess(ci.index("npm run test:api-compat"), ci.index("npm run test:data-quality"))
        self.assertLess(ci.index("npm run test:data-quality"), ci.index("npm run build"))
        self.assertLess(ci.index("npm run build"), ci.index("npm run smoke:frontend"))
        self.assertIn("npx playwright install --with-deps chromium", ci)

    def test_delivery_verification_matches_ci_quality_gate(self) -> None:
        verifier = (self.ROOT / "scripts/verify_delivery.py").read_text(encoding="utf-8")

        for command in (
            '"ops drill readiness preflight"',
            '"secret hygiene gate"',
            '"backend unit tests"',
            '"backend coverage gate"',
            '"research review smoke"',
            '"research review readiness check"',
            '"research review runner check"',
            '"frontend lint"',
            '"frontend type-check"',
            '"frontend API compatibility"',
            '"frontend data quality contract"',
            '"frontend build"',
            '"frontend smoke"',
        ):
            self.assertIn(command, verifier)

        self.assertIn("scripts/ops/verify_ops_drill_readiness.py", verifier)
        self.assertIn("scripts/verify_secret_hygiene.py", verifier)
        self.assertIn("backend/scripts/review_tracker_run.py", verifier)
        self.assertIn("--include-readiness", verifier)
        self.assertIn("test:data-quality", verifier)
        self.assertLess(verifier.index('"ops drill readiness preflight"'), verifier.index('"backend compile"'))
        self.assertLess(verifier.index('"secret hygiene gate"'), verifier.index('"backend compile"'))
        self.assertLess(verifier.index('"research review smoke"'), verifier.index('"research review runner check"'))
        self.assertLess(verifier.index('"research review readiness check"'), verifier.index('"research review runner check"'))
        self.assertLess(verifier.index('"frontend API compatibility"'), verifier.index('"frontend data quality contract"'))
        self.assertLess(verifier.index('"frontend build"'), verifier.index('"frontend smoke"'))

    def test_project_issues_tracks_execution_status(self) -> None:
        issues = (self.ROOT / "PROJECT_ISSUES.md").read_text(encoding="utf-8")

        self.assertIn("## 八、执行状态", issues)
        self.assertRegex(issues, re.compile(r"P0.*已完成", re.S))
        self.assertIn("scripts/ops/verify_ops_drill_readiness.py", issues)
        self.assertIn("scripts/verify_secret_hygiene.py", issues)
        self.assertIn("真实 GitHub Actions/部署环境", issues)
        self.assertIn("剩余 1 项", issues)
        self.assertIn("仍未完成", issues)


if __name__ == "__main__":
    unittest.main()
