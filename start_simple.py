#!/usr/bin/env python3
"""
简化版股票数据平台启动脚本
适用于开发和测试环境
"""

import subprocess
import sys
import os
from pathlib import Path

def check_python():
    """检查Python版本"""
    version = sys.version_info
    if version.major < 3 or version.minor < 8:
        print(f"错误: 需要Python 3.8+，当前版本: {version.major}.{version.minor}")
        return False
    print(f"Python版本: {version.major}.{version.minor}")
    return True

def install_requirements():
    """安装必要的依赖"""
    try:
        import fastapi
        import uvicorn
        print("核心依赖已安装")
        return True
    except ImportError:
        print("正在安装依赖...")
        requirements = Path("backend/services/market_service/requirements.txt")
        if requirements.exists():
            result = subprocess.run([
                sys.executable, "-m", "pip", "install", "-r", str(requirements)
            ], capture_output=True, text=True)
            if result.returncode == 0:
                print("依赖安装完成")
                return True
            else:
                print(f"依赖安装失败: {result.stderr}")
                return False
        else:
            print("找不到依赖文件")
            return False

def start_market_service():
    """启动行情服务"""
    print()
    print("启动行情服务...")
    env = os.environ.copy()
    env["LOG_LEVEL"] = "INFO"
    service_dir = Path("backend/services/market_service/app")
    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"],
            cwd=service_dir,
            env=env
        )
        print(f"行情服务已启动: http://localhost:8000")
        print(f"API文档: http://localhost:8000/docs")
        return process
    except Exception as e:
        print(f"启动失败: {e}")
        return None

def start_user_service():
    """启动用户服务"""
    print()
    print("启动用户服务...")
    env = os.environ.copy()
    env["LOG_LEVEL"] = "INFO"
    service_dir = Path("backend/services/user_service/app")
    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"],
            cwd=service_dir,
            env=env
        )
        print(f"用户服务已启动: http://localhost:8002")
        print(f"API文档: http://localhost:8002/docs")
        return process
    except Exception as e:
        print(f"启动失败: {e}")
        return None

def main():
    print("股票数据分析平台启动")
    print("=" * 50)
    if not check_python():
        return
    if not install_requirements():
        return
    processes = []
    try:
        market_process = start_market_service()
        if market_process:
            processes.append(market_process)
        frontend_process = start_user_service()
        if frontend_process:
            processes.append(frontend_process)
        if processes:
            print("\n平台已启动！")
            print("访问地址:")
            print("  行情API: http://localhost:8000")
            print("  用户API: http://localhost:8002")
            print("\n按 Ctrl+C 停止服务")
            try:
                import time
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\n正在停止服务...")
    finally:
        for process in processes:
            if process:
                try:
                    process.terminate()
                except:
                    pass

if __name__ == "__main__":
    main()