#!/usr/bin/env python
"""启动所有服务 - SQLite 本地模式 (无需 Docker)"""
import os
import sys
import subprocess
import time
import signal

# 设置 SQLite 模式
os.environ["USE_SQLITE"] = "true"
os.environ["DB_HOST"] = ""

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
PYTHON = sys.executable

processes = []


def run_service(name, script_rel_path, port, cwd=None):
    """运行一个服务"""
    if cwd is None:
        cwd = PROJECT_ROOT
    script_path = os.path.join(PROJECT_ROOT, script_rel_path)
    print(f"[{name}] Starting on port {port}...")
    env = os.environ.copy()
    proc = subprocess.Popen(
        [PYTHON, script_path],
        cwd=cwd,
        env=env,
        creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0,
    )
    processes.append((name, proc))
    return proc


def main():
    print("=" * 50)
    print("Stock Analysis Platform - SQLite Mode (No Docker)")
    print("=" * 50)
    print()

    # 1. User Service (8002)
    run_service("User Service", "backend/services/user_service/app/main.py", 8002)

    # 2. Market Service (8001)
    run_service("Market Service", "backend/services/market_service/app/main.py", 8001)

    # 3. Analysis Service (8003)
    run_service("Analysis Service", "backend/services/analysis_service/app/main.py", 8003)

    # 4. Frontend (5175) - Vite dev server
    print("[Frontend] Starting Vite dev server on port 5175...")
    env = os.environ.copy()
    frontend_dir = os.path.join(PROJECT_ROOT, "frontend/web")
    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
    proc = subprocess.Popen(
        [npm_cmd, "run", "dev"],
        cwd=frontend_dir,
        env=env,
        creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0,
    )
    processes.append(("Frontend", proc))

    print()
    print("=" * 50)
    print("All services starting...")
    print()
    print("Access URLs:")
    print("  - Frontend:         http://localhost:5175")
    print("  - Market API Docs:  http://localhost:8001/api/v1/docs")
    print("  - User API Docs:    http://localhost:8002/api/v1/docs")
    print("  - Analysis API Docs:http://localhost:8003/api/v1/docs")
    print()
    print("Analysis Endpoints (no auth):")
    print("  - Technical:  GET /api/v1/analysis/technical/{symbol}")
    print("  - Compare:    GET /api/v1/analysis/compare?symbols=A,B")
    print("  - Score:      GET /api/v1/analysis/score/{symbol}")
    print("  - Patterns:   GET /api/v1/analysis/patterns/{symbol}")
    print()
    print("Test Account:")
    print("  - Username: admin / Password: admin123 (admin role)")
    print("  - Username: test  / Password: test123  (free role)")
    print("=" * 50)
    print()
    print("Press Ctrl+C to stop all services")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
        for name, proc in processes:
            try:
                proc.terminate()
                print(f"[{name}] Stopped")
            except Exception:
                pass
        sys.exit(0)


if __name__ == "__main__":
    main()
