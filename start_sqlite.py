#!/usr/bin/env python
"""启动服务 - SQLite 临时模式 (无 Docker)"""
import os
import sys
import subprocess

os.environ["USE_SQLITE"] = "true"
os.environ["DB_HOST"] = ""

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

def start_market_service():
    """启动行情服务"""
    print("启动行情服务 :8001...")
    os.chdir(os.path.join(PROJECT_ROOT, "backend/services/market_service/app"))
    sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend/services/market_service/app"))
    sys.path.insert(0, PROJECT_ROOT)

    from main import app
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)

def start_user_service():
    """启动用户服务"""
    print("启动用户服务 :8002...")
    os.chdir(os.path.join(PROJECT_ROOT, "backend/services/user_service/app"))
    sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend/services/user_service/app"))
    sys.path.insert(0, PROJECT_ROOT)

    from main import app
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)

def start_frontend():
    """启动前端"""
    print("启动前端 :5175...")
    frontend_dir = os.path.join(PROJECT_ROOT, "frontend/web")
    subprocess.Popen(
        [sys.executable, "-m", "http.server", "5175"],
        cwd=frontend_dir,
        creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
    )

def main():
    print("=" * 50)
    print("股票分析平台 - SQLite 临时模式")
    print("=" * 50)
    print()
    print("服务地址:")
    print("  - 前端:       http://localhost:5175")
    print("  - 行情服务:   http://localhost:8001/api/v1/docs")
    print("  - 用户服务:   http://localhost:8002/api/v1/docs")
    print()
    print("按 Ctrl+C 停止所有服务")
    print("=" * 50)

    start_frontend()
    start_market_service()

if __name__ == "__main__":
    main()