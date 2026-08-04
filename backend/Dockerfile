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
ENV PORT=8000
EXPOSE 8000

# Shell form so $PORT expands: Render/Railway/Fly assign the port at runtime and
# the container must bind to it.
#
# --proxy-headers is not optional behind their routers. Without it every request
# arrives with the proxy's IP, so the per-IP rate limiter would treat all
# patients as one client and lock everyone out at the same time.
#
# Migrations + seeding run inside the app's own startup event (backend/app/main.py).
CMD python -m uvicorn backend.app.main:app \
    --host 0.0.0.0 --port ${PORT:-8000} \
    --proxy-headers --forwarded-allow-ips='*'
