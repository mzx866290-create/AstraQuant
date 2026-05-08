# Monitoring Runbook

## Dashboards

Grafana provisioning loads three dashboards from `infra/grafana/dashboards`:

- `business-overview.json`: service presence, HTTP request rate, HTTP 5xx rate, latency, in-flight requests.
- `crawler-health.json`: scheduler running/error state, task run rate, saved row rate, latest task status.
- `system-overview.json`: scrape target health, scrape samples, Prometheus TSDB series, process CPU and RSS.

## Alerts

### ServiceMetricsTargetDown

Check `docker compose ps`, then inspect the target service logs and `/health`. If only `/metrics` is down, verify the service calls `install_metrics`.

### PrometheusTargetMissing

Check `infra/prometheus/prometheus.yml`, service DNS names, and whether the target service exists in the active compose file.

### ServiceMetricsScrapeFailing

Open the service `/metrics` endpoint from inside the Prometheus container. A reachable endpoint with zero samples usually means metrics middleware failed to install.

### ServiceHttp5xxRateHigh

Inspect the service logs around the alert window and correlate with request path labels in Grafana.

### DataCrawlerSchedulerStopped

Check `DATA_CRAWLER_ENABLE_SCHEDULER`, `/status`, and the `data-crawler` logs. Restart only after confirming the symbol pool is not empty.

### DataCrawlerSchedulerError

Inspect `/status` and the scheduler error field. Confirm Redis, PostgreSQL, and ClickHouse are healthy before restarting the crawler.

### DataCrawlerTaskFailing

Use the task label to locate the failing ETL path. Check source availability, row counts, and ClickHouse write errors before manually rerunning the task.

## Alert Delivery

Alertmanager reads `ALERT_WEBHOOK_URL` from the environment and expands it into `infra/alertmanager/alertmanager.yml`. The deployment environment must provide the real receiver URL for Feishu, DingTalk, Slack, or another compatible webhook endpoint. The webhook receiver should acknowledge both firing and resolved notifications.

Use `scripts/ops/alert_webhook_drill.py` before production changes. It defaults to dry-run and only sends when `--send` is passed.

Examples:

```bash
python scripts/ops/alert_webhook_drill.py --url "$ALERT_WEBHOOK_URL" --dry-run
python scripts/ops/alert_webhook_drill.py --url "$ALERT_WEBHOOK_URL" --send --status both --record-output alert-webhook-drill-record.md
python scripts/ops/alert_webhook_drill.py --record-template
```

GitHub Actions also exposes a manual `Alert Webhook Drill` workflow. Keep the
repository secret `ALERT_WEBHOOK_URL` set to the production receiver before
choosing `send=true`. The workflow always uploads an
`alert-webhook-drill-record` artifact prefilled with the run URL, send mode,
status input, and HTTP responses; fill it with the observed firing and resolved
delivery times after the exercise.

Before archiving the filled record, validate it locally:

```bash
python scripts/ops/validate_alert_webhook_drill_record.py <alert-webhook-drill-record.md>
```

After preparing the drill archive, finalize the completed evidence package:

```bash
python scripts/ops/finalize_ops_drill_archive.py \
  <archive-dir> \
  --summary-json <archive-dir>.finalize-summary.json
```

Recommended archive layout:

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

Only move the archive into the release or operations log after the archive
finalizer prints `OK` and creates the manifest, seal marker, zip package, and
zip checksum. Later integrity checks can use:

```bash
python scripts/ops/finalize_ops_drill_archive.py \
  --verify <archive-dir> \
  --summary-json <archive-dir>.verify-summary.json
python scripts/ops/finalize_ops_drill_archive.py \
  --verify-package <archive.zip> \
  --summary-json <archive.zip>.summary.json
```

Before a real alert/deployment drill, run
`python scripts/ops/ops_drill_archive_smoke.py` as a local pre-check for the
archive scripts. It validates the temporary prepare/finalize/verify/package
chain only; real webhook firing/resolved delivery still requires the manual
record below.

Also run `python scripts/ops/verify_ops_drill_readiness.py --env-file .env.production`
before the real drill window to confirm workflow, compose, and env prerequisites
are present.

For the full download, prepare, validate, and archive procedure, use
`docs/ops/ops-drill-archive-runbook.md`.

## Alert Webhook Drill Record

Copy this template into the incident/drill log for every real webhook exercise:

| Field | Value |
| --- | --- |
| 时间 | |
| 负责人 | |
| 接收端 | |
| GitHub Actions run URL | |
| `send` mode | |
| `status` input | |
| HTTP firing response | |
| HTTP resolved response | |
| 触发告警 | |
| 收到时间 | |
| 恢复告警 | |
| Artifact `alert-webhook-drill-record` | |
| 结论 | |
