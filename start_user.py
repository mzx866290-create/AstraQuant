#!/usr/bin/env python
"""Start user-service using app object directly (avoids uvicorn subprocess issue on Windows)"""
import os, sys
sys.path.insert(0, r"F:/项目/Demo4")
os.environ.update({
    "DB_USER": "stockadmin", "DB_PASS": "changeme",
    "DB_HOST": "localhost", "REDIS_HOST": "localhost",
    "CLICKHOUSE_HOST": "localhost", "LOG_LEVEL": "INFO",
})
app_dir = r"F:/项目/Demo4/backend/services/user_service/app"
sys.path.insert(0, app_dir)
os.chdir(app_dir)

from main import app
import uvicorn
uvicorn.run(app, host="0.0.0.0", port=8002, reload=False)
