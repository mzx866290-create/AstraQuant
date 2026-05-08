@echo off
echo start_services.bat is a legacy compatibility wrapper.
echo Official container startup: docker compose up -d
echo Official local startup: python scripts/start_local.py
echo.
docker compose up -d
