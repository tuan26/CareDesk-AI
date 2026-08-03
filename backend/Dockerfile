# Build from the repo root: docker build -f backend/Dockerfile .
# (the app imports itself as `backend.app...`, so /app must contain the
# `backend/` package, not just its contents)
FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ backend/

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# Migrations + seeding run inside the app's own startup event (see
# backend/app/main.py) - no separate migrate step needed here.
CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
