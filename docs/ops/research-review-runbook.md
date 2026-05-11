# Research Review Runbook

This runbook verifies the A-share research orchestration loop in a real environment.

The goal is not to prove prediction quality. The goal is to prove the operational loop works:

`recommendations -> research_observations -> pending reviews -> observation_reviews -> review report/readiness`

## Preconditions

- Analysis service can connect to the target database.
- Migrations have been applied:

```bash
alembic upgrade head
```

- The following tables exist in the target database:

```text
research_observations
observation_reviews
```

- Market quote data source is reachable by the analysis service.
- Admin user can access `/api/v1/admin/stats/*`.

## Local Non-DB Smoke

Run this before touching a real environment. It uses in-memory fakes and does not require market data:

```bash
venv\Scripts\python.exe backend/scripts/review_smoke.py
```

Expected:

```text
"status": "ok"
"saved": 1
"pending": 1
"created": 1
```

## Production Readiness Check

Run readiness against the actual service environment:

```bash
venv\Scripts\python.exe backend/scripts/review_readiness_check.py --date 2026-05-11
```

Use strict mode for release verification:

```bash
venv\Scripts\python.exe backend/scripts/review_readiness_check.py --date 2026-05-11 --strict
```

Status meanings:

- `tables_missing`: migrations or database target are not ready.
- `no_observations`: no recommendation snapshot has been saved yet.
- `pending_reviews`: snapshots exist and at least one T+1/T+5/T+20 review is due.
- `no_pending_reviews`: snapshots exist, but no review is due for the selected date.
- `reviewed`: at least one review exists and no selected-offset review is currently pending.
- `error`: readiness query failed; check service logs and DB connectivity.

## End-To-End Verification

1. Generate recommendations with research fields:

```http
GET /api/v1/analysis/score/batch/recommend?market=ALL&limit=10&strategy=auto&include_evidence=true&include_debate=true
```

Expected:

- Response `status` is `ok`.
- `active_strategy.id` is present.
- Each returned item has `strategy_id`.
- At least one returned item has `veto_result`.
- If evidence is enabled, items include `evidence_chain`.

2. Confirm snapshots were written:

```bash
venv\Scripts\python.exe backend/scripts/review_readiness_check.py --date 2026-05-11
```

Expected:

- `tables.research_observations` is `true`.
- `summary.observations` is greater than `0`.
- `latest_snapshot_date` is populated.

3. Run pending reviews for the target date:

```bash
venv\Scripts\python.exe backend/scripts/review_tracker_run.py --date 2026-05-11 --offsets T+1 --include-readiness
```

Expected:

- `run_pending_reviews.status` is `ok` or `no_pending_reviews`.
- If pending items existed, `created` is greater than `0`.
- `review_readiness.status` is not `tables_missing` or `error`.

4. Check readiness again:

```bash
venv\Scripts\python.exe backend/scripts/review_tracker_run.py --date 2026-05-11 --report-only --require-reviewed --require-no-pending
```

Expected:

- Status is not `tables_missing`, `error`, or `no_observations`.
- `summary.reviews` is greater than `0` after due reviews have run.
- Exit code `2` means the environment is not ready; exit code `3` means the environment is ready but no review records exist yet; exit code `4` means selected offsets still have pending reviews.

If you only need readiness without the review report, use:

```bash
venv\Scripts\python.exe backend/scripts/review_readiness_check.py --date 2026-05-11 --require-reviewed --require-no-pending
```

5. Verify Admin UI:

- Open Admin Stats.
- Check `复盘链路 Readiness`.
- Confirm table chips are `ok`.
- Confirm observations/reviews/pending counts match the CLI readiness output.
- Confirm `研究复盘概览` and `策略复盘表现` show report data after reviews exist.

## Scheduler

The scheduler is controlled by environment variables:

```bash
REVIEW_SCHEDULER_ENABLED=true
REVIEW_SCHEDULER_INTERVAL_SECONDS=3600
```

Admin endpoints:

```http
GET  /api/v1/admin/stats/review-scheduler
GET  /api/v1/admin/stats/review-readiness
POST /api/v1/admin/stats/review-scheduler/run-once?review_date=2026-05-11
GET  /api/v1/admin/stats/review-report
GET  /api/v1/admin/stats/review-factor-report
```

## Troubleshooting

- If status is `tables_missing`, verify migrations and database URL.
- If status is `no_observations`, call the recommendation endpoint and confirm `research_pipeline.save_observation_snapshots` can write to DB.
- If status remains `pending_reviews` after running review, check quote source errors and `run_pending_reviews.items`.
- If Admin UI is empty but CLI is healthy, check admin auth, API base URL, and `/api/v1/admin/stats/review-readiness`.
- If review counts do not change, verify the target `--date` matches T+1/T+5/T+20 relative to `snapshot_date`.

## Delivery Gate

Local delivery verification now includes the non-DB research review smoke and frontend recommendation contract:

```bash
python scripts/verify_delivery.py
```
