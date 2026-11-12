FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock

COPY app ./app
COPY data ./data
COPY tests ./tests
COPY pytest.ini ./pytest.ini

EXPOSE 8000

# Hosts like Render pass the port in $PORT; docker compose uses 8000.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
