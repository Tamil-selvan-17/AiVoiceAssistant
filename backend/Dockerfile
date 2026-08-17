FROM python:3.11-slim

WORKDIR /app

# System deps: curl for the healthcheck, ffmpeg for audio format conversion
# (browser-recorded webm/ogg -> normalized WAV for speech-to-text/VAD).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# frontend/ is copied in alongside backend/ by docker-compose / build context;
# see docker-compose.yml at the repo root for local development.

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/api/health || exit 1

# Render (and most PaaS providers) inject $PORT at runtime.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
