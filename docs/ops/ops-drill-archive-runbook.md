# Ops Drill Archive Runbook

Use this runbook after a real GitHub Actions and deployment drill. The repository
keeps templates and validators only; store completed drill evidence in the
release ticket, operations knowledge base, or immutable object storage.

Before the real drill window, run local preflight checks in this order:

```bash
python scripts/ops/verify_ops_drill_readiness.py --env-file .env.production
python scripts/verify_secret_hygiene.py
python scripts/ops/ops_drill_archive_smoke.py
```

When `.env.production` is available on the deployment host, include
`--env-file .env.production` to check required production keys without printing
secret values. The smoke uses temporary sample records only; it proves the local
archive script chain, not the real GitHub Actions, alert, or deployment evidence.

## 1. Download Artifacts

Download both GitHub Actions artifacts:

- `ci-deployment-drill-record`
- `alert-webhook-drill-record`

From the GitHub UI, download and unzip each artifact into a temporary directory.
With GitHub CLI:

```bash
gh run download <ci-run-id> -n ci-deployment-drill-record -D .tmp/ci-artifact
gh run download <alert-run-id> -n alert-webhook-drill-record -D .tmp/alert-artifact
```

## 2. Prepare Archive

Create the standard archive directory:

```bash
python scripts/ops/prepare_ops_drill_archive.py \
  --ci-record .tmp/ci-artifact \
  --alert-record .tmp/alert-artifact \
  --output-root ops-drills \
  --date <yyyy-mm-dd> \
  --environment production \
  --app-version <app-version>
```

The script creates:

```text
ops-drills/<yyyy-mm-dd>-production-<app-version>/
  raw/
    ci-deployment-drill-record/
      ci-deployment-drill-record.md
    alert-webhook-drill-record/
      alert-webhook-drill-record.md
  completed/
    ci-deployment-drill-record.md
    alert-webhook-drill-record.md
  README.md
  validation.txt     # pending until finalization
```

If you need to recreate an unfinalized archive, pass `--force`. Once `.sealed`
exists, the prepare script refuses to overwrite the archive; create a new
archive name instead.

## 3. Complete Records

Edit only the files under `completed/`. Keep `raw/` unchanged as the downloaded
artifact source. Fill the observed alert delivery timestamps, deployment smoke
evidence, rollback evidence, final conclusion, and owners.

Do not paste real webhook URLs or tokens into either record.

## 4. Finalize

Optional local pre-check before a real drill archive is finalized:

```bash
python scripts/ops/ops_drill_archive_smoke.py
```

The smoke script creates sample records in a temporary workspace, runs prepare,
finalize, extracted archive verification, and zip-only verification, then
removes the workspace by default. Pass `--keep` only when you need to inspect the
generated sample archive. This smoke verifies the local script chain only; it
does not replace real GitHub Actions, webhook delivery, deployment smoke, or
rollback evidence.

After both files under `completed/` are filled, finalize the archive:

```bash
python scripts/ops/finalize_ops_drill_archive.py \
  ops-drills/<yyyy-mm-dd>-production-<app-version> \
  --summary-json ops-drills/<yyyy-mm-dd>-production-<app-version>.finalize-summary.json
```

The finalizer validates `completed/`, scans `raw/`, `completed/`, `README.md`,
and `validation.txt` for sensitive webhook URL or token evidence, writes
`validation.txt`, `manifest.json`, `manifest.sha256`, and `.sealed`, then creates
`<archive>.zip` plus `<archive>.zip.sha256` next to the archive directory. Only
archive the package after the finalizer prints `OK`.

`--summary-json` is optional. Use it for CI, release ticket, or operations-log
automation; it records the operation mode, status, archive name, paths, and
issues/errors when present. Keep this JSON outside the sealed archive directory.
It is a machine-readable log sidecar, not manifest-covered evidence.

Finalized layout:

```text
ops-drills/<yyyy-mm-dd>-production-<app-version>/
  raw/
  completed/
  README.md
  validation.txt
  manifest.json
  manifest.sha256
  .sealed
ops-drills/<yyyy-mm-dd>-production-<app-version>.zip
ops-drills/<yyyy-mm-dd>-production-<app-version>.zip.sha256
```

You can re-check either the extracted archive directory or the sealed zip
package:

```bash
python scripts/ops/finalize_ops_drill_archive.py \
  --verify ops-drills/<yyyy-mm-dd>-production-<app-version> \
  --summary-json ops-drills/<yyyy-mm-dd>-production-<app-version>.verify-summary.json
python scripts/ops/finalize_ops_drill_archive.py --verify-package ops-drills/<yyyy-mm-dd>-production-<app-version>.zip --summary-json ops-drills/<yyyy-mm-dd>-production-<app-version>.package-verify-summary.json
```

For troubleshooting, run the individual validators directly:

```bash
python scripts/ops/validate_ci_deployment_drill_record.py completed/ci-deployment-drill-record.md
python scripts/ops/validate_alert_webhook_drill_record.py completed/alert-webhook-drill-record.md
python scripts/ops/validate_ops_drill_archive.py completed
```

## 5. Archive

Store the completed package outside the source repository, for example:

```text
ops-drills/<env>/<yyyy-mm-dd>/<app-version>/
```

Acceptable stores include the release ticket, operations knowledge base, or
immutable object storage. Keep the zip package, `<archive>.zip.sha256`,
`manifest.json`, `manifest.sha256`, and `.sealed` together with the archive and
enable object-lock/WORM retention when the storage platform supports it. Keep
only redacted examples in the repository. Keep any `*.summary.json` files with
the release or CI log as operational metadata; they should not be inserted into
the sealed archive directory after finalization.
