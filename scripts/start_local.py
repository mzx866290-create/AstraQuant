#!/usr/bin/env python
"""Start local development services with port cleanup and health checks.

This script is meant for the local SQLite/dev setup:
- market service:   8001
- user service:     8002
- analysis service: 8003
- frontend:         5175
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
PORTS = [8001, 8002, 8003, 5175]
PUBLIC_URL = "http://mzxstock.duckdns.org:5175/"


def _run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd or ROOT), capture_output=True, text=True, shell=False)


def pids_on_port(port: int) -> set[int]:
    pids: set[int] = set()
    if os.name == "nt":
        result = _run(["netstat", "-ano", "-p", "tcp"])
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) < 5:
                continue
            local_addr = parts[1]
            state = parts[3]
            pid = parts[4]
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
            try:
                if os.name == "nt":
                    _run(["taskkill", "/PID", str(pid), "/F", "/T"])
                else:
                    os.kill(pid, signal.SIGTERM)
            except Exception as exc:
                print(f"[warn] failed to stop pid {pid}: {exc}")


def start_process(name: str, cmd: list[str], log_name: str, cwd: Path | None = None) -> subprocess.Popen:
    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    stdout = open(log_dir / f"{log_name}.log", "a", encoding="utf-8")
    stderr = open(log_dir / f"{log_name}_err.log", "a", encoding="utf-8")
    env = os.environ.copy()
    env["USE_SQLITE"] = "true"
    env["DB_HOST"] = "localhost"
    env.setdefault("LOG_LEVEL", "INFO")
    print(f"[start] {name}: {' '.join(cmd)}")
    return subprocess.Popen(cmd, cwd=str(cwd or ROOT), env=env, stdout=stdout, stderr=stderr)


def probe(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def wait_for(name: str, url: str, seconds: int = 45) -> bool:
    print(f"[check] {name}: {url}")
    deadline = time.time() + seconds
    while time.time() < deadline:
        if probe(url):
            print(f"[ok] {name}")
            return True
        time.sleep(1)
    print(f"[fail] {name} did not become healthy")
    return False


def main() -> int:
    os.chdir(ROOT)
    print("Stock platform local startup")
    print("=" * 36)
    stop_ports()
    time.sleep(1)

    processes = [
        start_process("market-service", [PYTHON, "backend/services/market_service/app/main.py"], "market_service"),
        start_process("user-service", [PYTHON, "backend/services/user_service/app/main.py"], "user_service"),
        start_process("analysis-service", [PYTHON, "backend/services/analysis_service/app/main.py"], "analysis_service"),
    ]
    npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
    processes.append(
        start_process(
            "frontend",
            [npm_cmd, "run", "dev", "--", "--host", "0.0.0.0", "--port", "5175", "--strictPort"],
            "frontend_vite",
            ROOT / "frontend/web",
        )
    )

    checks = [
        wait_for("market-service", "http://localhost:8001/health"),
        wait_for("user-service", "http://localhost:8002/health"),
        wait_for("analysis-service", "http://localhost:8003/health"),
        wait_for("frontend", "http://localhost:5175/"),
    ]

    print("=" * 36)
    print("Frontend: http://localhost:5175/")
    print(f"Public URL: {PUBLIC_URL}")
    print("Daily observation: http://localhost:5175/")
    print("System health: http://localhost:8003/api/v1/analysis/system-health")
    print("Logs: ./logs")
    if not all(checks):
        print("One or more services failed health checks. See logs above.")
        return 1
    print("All services are healthy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
