# DemandIQ — single-service image: FastAPI serves the API *and* the React build.
#
# Why one service: the frontend and backend only talk to each other through the
# Vite dev proxy locally. Shipping them as one container means there is nothing
# to proxy, no CORS to configure, and no second URL to keep in sync.
#
# Build:  docker build -t demandiq .
# Run:    docker run -p 8000:8000 -e ANTHROPIC_API_KEY=sk-... demandiq

# ── Stage 1: build the React app ──────────────────────────────────────────────
FROM node:20-slim AS frontend
WORKDIR /build

# Copy manifests first so `npm ci` is cached until dependencies actually change.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


# ── Stage 2: the runtime ──────────────────────────────────────────────────────
FROM python:3.12-slim

# poppler-utils provides pdftoppm, which pdf2image shells out to when rasterising
# an uploaded count sheet for vision extraction. Without it every PDF upload
# fails at runtime — the wheel installs fine and gives no build-time warning.
RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Only the lean requirements. The geo stack (requirements-forecasting.txt) is
# deliberately excluded: its imports are lazy, so the app starts without it and
# /forecast/ingest-match returns 503 rather than crashing.
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
# app.py resolves the build at ../frontend/dist relative to itself.
COPY --from=frontend /build/dist ./frontend/dist

# Matplotlib renders the line diagrams headlessly; no display exists here.
ENV MPLBACKEND=Agg
# Unbuffered so logs reach the platform's log viewer immediately.
ENV PYTHONUNBUFFERED=1

WORKDIR /app/backend

# The platform supplies $PORT; app.py already honours it and defaults to 8000.
EXPOSE 8000
CMD ["python", "app.py"]
