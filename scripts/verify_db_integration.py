#!/usr/bin/env python
"""Verify the docker-compose backed database integration test services."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "docker-compose.test.yml"
SERVICES = ("postgres-test", "clickhouse-test", "redis-test")


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        cmd,
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        shell=False,
    )
    if check and result.returncode != 0:
        if result.stdout:
            print(result.stdout.rstrip())
        raise subprocess.CalledProcessError(result.returncode, cmd, output=result.stdout)
    return result


def compose_cmd(*args: str) -> list[str]:
    return ["docker", "compose", "-f", str(COMPOSE_FILE), *args]


def skip_or_fail(message: str, require_docker: bool) -> int:
    prefix = "[fail]" if require_docker else "[skip]"
    print(f"{prefix} {message}")
    return 1 if require_docker else 0


def docker_available(require_docker: bool) -> bool:
    if shutil.which("docker") is None:
        raise SystemExit(skip_or_fail("docker executable is not available", require_docker))

    result = run(["docker", "compose", "version"], check=False)
    if result.returncode != 0:
        raise SystemExit(skip_or_fail("docker compose is not available", require_docker))
    print(f"[ok] {result.stdout.strip()}")

    result = run(["docker", "info"], check=False)
    if result.returncode != 0:
        raise SystemExit(skip_or_fail("docker daemon is not available", require_docker))
    print("[ok] docker daemon is available")
    return True


def container_id(service: str) -> str:
    result = run(compose_cmd("ps", "-q", service), check=False)
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(f"{service} container is not running")
    return result.stdout.strip().splitlines()[0]


def health_status(service: str) -> str:
    cid = container_id(service)
    result = run(
        ["docker", "inspect", "-f", "{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}", cid],
        check=False,
    )
    if result.returncode != 0:
        return "unknown"
    return result.stdout.strip()


def wait_for_healthy(timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_statuses: dict[str, str] = {}

    while time.monotonic() < deadline:
        last_statuses = {service: health_status(service) for service in SERVICES}
        if all(status == "healthy" for status in last_statuses.values()):
            print("[ok] all database integration services are healthy")
            return
        print("[wait] " + ", ".join(f"{service}={status}" for service, status in last_statuses.items()))
        time.sleep(5)

    statuses = ", ".join(f"{service}={status}" for service, status in last_statuses.items())
    raise TimeoutError(f"services did not become healthy within {timeout_seconds}s: {statuses}")


def smoke_postgres() -> None:
    db_name = os.environ.get("TEST_DB_NAME", "stock_platform_test")
    db_user = os.environ.get("TEST_DB_USER", "stocktest")
    db_pass = os.environ.get("TEST_DB_PASS", "stocktest")
    run(
        compose_cmd(
            "exec",
            "-T",
            "-e",
            f"PGPASSWORD={db_pass}",
            "postgres-test",
            "psql",
            "-U",
            db_user,
            "-d",
            db_name,
            "-c",
            "SELECT 1",
        )
    )
    print("[ok] PostgreSQL SELECT 1")


def smoke_clickhouse() -> None:
    database = os.environ.get("TEST_CLICKHOUSE_DATABASE", "default")
    user = os.environ.get("TEST_CLICKHOUSE_USER", "default")
    password = os.environ.get("TEST_CLICKHOUSE_PASSWORD", "")
    cmd = compose_cmd(
        "exec",
        "-T",
        "clickhouse-test",
        "clickhouse-client",
        "--host",
        "localhost",
        "--port",
        "9000",
        "--database",
        database,
        "--user",
        user,
    )
    if password:
        cmd.extend(["--password", password])
    cmd.extend(["--query", "SELECT 1"])
    run(cmd)
    print("[ok] ClickHouse SELECT 1")


def smoke_redis() -> None:
    result = run(compose_cmd("exec", "-T", "redis-test", "redis-cli", "PING"))
    if "PONG" not in result.stdout:
        raise RuntimeError(f"Redis PING did not return PONG: {result.stdout.strip()}")
    print("[ok] Redis PING")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-docker", action="store_true", help="fail instead of skipping when Docker is unavailable")
    parser.add_argument("--timeout", type=int, default=180, help="seconds to wait for service healthchecks")
    parser.add_argument("--no-cleanup", action="store_true", help="leave compose services running after verification")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    docker_available(args.require_docker)

    try:
        run(compose_cmd("up", "-d", *SERVICES))
        wait_for_healthy(args.timeout)
        smoke_postgres()
        smoke_clickhouse()
        smoke_redis()
    finally:
        if not args.no_cleanup:
            run(compose_cmd("down", "--remove-orphans", "-v"), check=False)

    print("[ok] database integration verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
