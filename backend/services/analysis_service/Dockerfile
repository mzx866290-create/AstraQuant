FROM python:3.11-slim

WORKDIR /app

COPY backend/services/analysis_service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/shared /backend/shared
COPY backend/services /backend/services
COPY backend/services/analysis_service /app

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=3)" || exit 1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
