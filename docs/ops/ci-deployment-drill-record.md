# CI And Deployment Drill Record

Use this record after a real GitHub Actions and deployment exercise. Keep the
filled copy in the release or operations log so every production readiness claim
has evidence attached.

The CI workflow uploads a draft `ci-deployment-drill-record` artifact after the
`db-integration` and `verify` jobs finish. Use that artifact as the starting
point, then fill in the real alert drill, production smoke, rollback, and final
decision fields after the deployment exercise.

Generate a filled copy with `python scripts/ops/render_ci_deployment_drill_record.py --output <record.md>`.
Unset fields are rendered as blank cells for manual completion.

Before archiving the filled record, validate it locally:

```bash
python scripts/ops/validate_ci_deployment_drill_record.py <record.md>
```

The validator fails when required evidence is still blank, left as a template
choice, marked as skipped/failed/cancelled, or when the final production-ready
conclusion is not a clear pass. Store only a passing record as formal drill
evidence.

When both GitHub Actions artifacts have been downloaded and completed, finalize
the evidence package:

```bash
python scripts/ops/finalize_ops_drill_archive.py \
  <archive-dir> \
  --summary-json <archive-dir>.finalize-summary.json
```

The finalizer validates the two records, scans for sensitive webhook/token
evidence, writes `validation.txt`, `manifest.json`, `manifest.sha256`, and
`.sealed`, then creates `<archive>.zip` plus `<archive>.zip.sha256`.

Use a single release-scoped directory so the finalizer can find both records:

```text
ops-drills/<yyyy-mm-dd>-production-<app-version>/
  raw/
  completed/
    ci-deployment-drill-record.md
    alert-webhook-drill-record.md
  validation.txt
  manifest.json
  manifest.sha256
  .sealed
ops-drills/<yyyy-mm-dd>-production-<app-version>.zip
ops-drills/<yyyy-mm-dd>-production-<app-version>.zip.sha256
```

After finalization, use `python scripts/ops/finalize_ops_drill_archive.py --verify <archive-dir>`
or `python scripts/ops/finalize_ops_drill_archive.py --verify-package <archive.zip>`
to re-check the manifest, seal marker, zip package, checksum, and optional
machine-readable summary before moving evidence into the release or operations
log.

Before a real drill, run `python scripts/ops/verify_ops_drill_readiness.py --env-file .env.production`
and `python scripts/verify_secret_hygiene.py`, then run
`python scripts/ops/ops_drill_archive_smoke.py` to verify the local
prepare/finalize/verify/package flow with temporary sample records. The smoke is
only a local script-chain check and does not replace real GitHub Actions, alert,
or production deployment evidence.

For the full download, prepare, validate, and archive procedure, use
`docs/ops/ops-drill-archive-runbook.md`.

## Summary

| Field | Value |
| --- | --- |
| Drill date (UTC) | |
| Owner | |
| Repository | |
| Commit SHA | |
| APP_VERSION | |
| Environment | |
| Final decision | pass / fail / follow-up required |

## GitHub Actions Evidence

| Check | Evidence |
| --- | --- |
| CI workflow run URL | |
| `db-integration` job result | |
| PostgreSQL smoke result | |
| ClickHouse smoke result | |
| Redis smoke result | |
| Backend unit test result | |
| Backend coverage gate result | |
| Frontend lint/type/build result | |
| Frontend smoke result | |
| Uploaded artifacts | |

## Alert Webhook Drill Evidence

| Check | Evidence |
| --- | --- |
| Alert Webhook Drill run URL | |
| `send` mode | false / true |
| Receiver | Feishu / DingTalk / Slack / other |
| Firing notification received at | |
| Resolved notification received at | |
| Artifact `alert-webhook-drill-record` | |

## Deployment Smoke Evidence

| Check | Command / Evidence |
| --- | --- |
| Deployment smoke | |
| Pull immutable images | `docker compose -f docker-compose.prod.yml --env-file .env.production pull` |
| Start services | `docker compose -f docker-compose.prod.yml --env-file .env.production up -d` |
| Service status | `docker compose -f docker-compose.prod.yml --env-file .env.production ps` |
| Market readiness | |
| Analysis metrics | |
| Prometheus readiness | |
| Grafana dashboards loaded | |
| Alertmanager config loaded | |

## Rollback Check

| Check | Evidence |
| --- | --- |
| Rollback check | |
| Previous known-good APP_VERSION | |
| Rollback command rehearsed | |
| Database migration rollback needed | no / yes, link plan |
| Rollback owner confirmed | |

## Result

| Field | Value |
| --- | --- |
| Production-ready conclusion | |
| Blocking issues | |
| Follow-up owner | |
| Follow-up due date | |
