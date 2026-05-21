#!/usr/bin/env python
"""Start the public-facing local deployment.

This keeps only the frontend static gateway exposed on 0.0.0.0:5175.
Backend services bind to 127.0.0.1 and are reached through the gateway.
"""
from __future__ import annotations

import base64
import os
import secrets
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
PORTS = [8001, 8002, 8003, 5175]
PUBLIC_URL = os.getenv("PUBLIC_URL", "https://yhang.cc.cd/")
PLACEHOLDER_SECRETS = {
    "",
    "your-super-secret-jwt-key-change-in-production",
    "dev-only-insecure-jwt-secret-change-me",
}


def _run(cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=str(cwd or ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
    )


def _load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _runtime_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(_load_env_file(ROOT / ".env"))
    env["AUTH_REQUIRED"] = "true"
    env["USE_SQLITE"] = "true"
    env["DB_HOST"] = "localhost"
    env["BIND_HOST"] = "127.0.0.1"
    env["FRONTEND_URL"] = PUBLIC_URL.rstrip("/")
    env["LOG_LEVEL"] = env.get("LOG_LEVEL", "INFO")

    if env.get("JWT_SECRET", "") in PLACEHOLDER_SECRETS or len(env.get("JWT_SECRET", "")) < 32:
        generated = base64.urlsafe_b64encode(secrets.token_bytes(48)).decode("ascii")
        env["JWT_SECRET"] = generated
        print("[secure] generated a runtime JWT_SECRET because .env has a placeholder")

    env["USER_SERVICE_URL"] = "http://127.0.0.1:8002"
    env["MARKET_SERVICE_URL"] = "http://127.0.0.1:8001"
    env["ANALYSIS_SERVICE_URL"] = "http://127.0.0.1:8003"
    env["FRONTEND_HOST"] = "0.0.0.0"
    env["FRONTEND_PORT"] = "5175"
    env["VITE_API_BASE_URL"] = ""
    env["REGISTRATION_ENABLED"] = env.get("REGISTRATION_ENABLED", "false")
    env["VITE_REGISTRATION_ENABLED"] = env["REGISTRATION_ENABLED"]
    env["ALLOW_CLOUDFLARE_INSIGHTS"] = env.get("ALLOW_CLOUDFLARE_INSIGHTS", "true")
    return env


def pids_on_port(port: int) -> set[int]:
    pids: set[int] = set()
    if os.name == "nt":
        result = _run(["netstat", "-ano", "-p", "tcp"])
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) < 5:
                continue
            local_addr, state, pid = parts[1], parts[3], parts[4]
            if local_addr.endswith(f":{port}") and state.upper() == "LISTENING" and pid.isdigit():
                pids.add(int(pid))
    else:
        result = _run(["sh", "-lc", f"lsof -ti tcp:{port} 2>/dev/null || true"])
        for line in result.stdout.splitlines():
            if line.strip().isdigit():
                pids.add(int(line.strip()))
    return pids


def stop_ports() -> None:
    current_pid = os.getpid()
    for port in PORTS:
        for pid in pids_on_port(port):
            if pid == current_pid:
                continue
            print(f"[stop] port {port}: pid {pid}")
            if os.name == "nt":
                _run(["taskkill", "/PID", str(pid), "/F", "/T"])
            else:
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass


def start_process(name: str, cmd: list[str], log_name: str, env: dict[str, str], cwd: Path | None = None) -> subprocess.Popen:
    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    stdout = open(log_dir / f"{log_name}.log", "a", encoding="utf-8")
    stderr = open(log_dir / f"{log_name}_err.log", "a", encoding="utf-8")
    print(f"[start] {name}: {' '.join(cmd)}")
    return subprocess.Popen(cmd, cwd=str(cwd or ROOT), env=env, stdout=stdout, stderr=stderr)


def probe(url: str, timeout: float = 3.0) -> int | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception:
        return None


def wait_for(name: str, url: str, expected: set[int], seconds: int = 60) -> bool:
    print(f"[check] {name}: {url}")
    deadline = time.time() + seconds
    while time.time() < deadline:
        status = probe(url)
        if status in expected:
            print(f"[ok] {name}: {status}")
            return True
        time.sleep(1)
    print(f"[fail] {name} did not become ready")
    return False


def build_frontend(env: dict[str, str]) -> None:
    npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
    print("[build] frontend")
    result = _run([npm_cmd, "run", "build"], cwd=ROOT / "frontend/web", env=env)
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        raise SystemExit(result.returncode)


def main() -> int:
    os.chdir(ROOT)
    env = _runtime_env()

    build_frontend(env)
    stop_ports()
    time.sleep(1)

    start_process("market-service", [PYTHON, "backend/services/market_service/app/main.py"], "market_service_public", env)
    start_process("user-service", [PYTHON, "backend/services/user_service/app/main.py"], "user_service_public", env)
    start_process("analysis-service", [PYTHON, "backend/services/analysis_service/app/main.py"], "analysis_service_public", env)
    start_process(
        "frontend-static-gateway",
        ["node", "scripts/serve_frontend_static.mjs"],
        "frontend_public",
        env,
    )

    checks = [
        wait_for("market-service", "http://127.0.0.1:8001/health", {200}),
        wait_for("user-service", "http://127.0.0.1:8002/health", {200}),
        wait_for("analysis-service", "http://127.0.0.1:8003/health", {200}),
        wait_for("frontend-static-gateway", "http://127.0.0.1:5175/health", {200}),
        wait_for("frontend-auth-gate", "http://127.0.0.1:5175/api/v1/stocks?limit=1", {401}),
    ]

    print("=" * 36)
    print(f"Public frontend: {PUBLIC_URL}")
    print("Public gateway: http://0.0.0.0:5175")
    print("Backend services: 127.0.0.1 only")
    print("Logs: ./logs/*_public*.log")
    return 0 if all(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
