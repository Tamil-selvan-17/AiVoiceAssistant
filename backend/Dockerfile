# Build context is the REPO ROOT, not backend/ -- so this image can bake in
# both backend/ and frontend/ and be deployed as a single web service (see
# docs/DEPLOYMENT.md and render.yaml). docker-compose.yml and Render's
# render.yaml both point their build context at the repo root and this
# Dockerfile at backend/Dockerfile.
FROM python:3.11-slim

WORKDIR /app

# System deps: curl for the healthcheck, ffmpeg for audio format conversion
# (browser-recorded webm/ogg -> normalized WAV for speech-to-text/VAD).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/pytest.ini ./pytest.ini
COPY frontend ./frontend

ENV PYTHONUNBUFFERED=1
ENV FRONTEND_DIR=/app/frontend
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/api/health || exit 1

# Render (and most PaaS providers) inject $PORT at runtime.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
