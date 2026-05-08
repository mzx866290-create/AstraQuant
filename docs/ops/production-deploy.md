# Production Deploy Runbook

## Scope

Production runs from `docker-compose.prod.yml`. It is intentionally separate from the local compose file so database, ClickHouse, Redis, and backend service ports are not exposed by accident.

Before a real release, run a local readiness check against the repository and
deployment env file:

```bash
python scripts/ops/verify_ops_drill_readiness.py --env-file .env.production
```

This preflight verifies the CI/workflow, ops scripts, compose files, and
production env placeholders before you pull or start anything.

## Release Inputs

- `APP_IMAGE_REGISTRY`: registry prefix that contains `market-service`, `user-service`, `analysis-service`, `data-crawler`, and `web` images.
- `APP_VERSION`: immutable image tag, usually a git SHA or semantic version.
- `.env.production`: generated from `.env.production.example` by the deployment secret manager.
- `ALERT_WEBHOOK_URL`: Alertmanager webhook endpoint.

## Deploy

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production pull
docker compose -f docker-compose.prod.yml --env-file .env.production up -d
docker compose -f docker-compose.prod.yml ps
```

## Verify

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production exec market-service python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/ready', timeout=3)"
docker compose -f docker-compose.prod.yml --env-file .env.production exec analysis-service python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/metrics', timeout=3)"
docker compose -f docker-compose.prod.yml --env-file .env.production exec prometheus wget -qO- http://localhost:9090/-/ready
```

## Rollback

Set `APP_VERSION` back to the previous known-good immutable tag, then rerun the deploy commands. Do not rollback database volumes with application rollback unless the release included a verified migration rollback plan.
