FROM python:3.11-slim

WORKDIR /app

COPY backend/services/analysis_service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/services/analysis_service /app

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health')" || exit 1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
