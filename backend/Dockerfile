# Build context is the REPO ROOT, not backend/ -- so this image can bake in
# both backend/ and frontend/ and be deployed as a single web service (see
# docs/DEPLOYMENT.md and render.yaml). docker-compose.yml and Render's
# render.yaml both point their build context at the repo root and this
# Dockerfile at backend/Dockerfile.
#
# Multi-stage build: `webrtcvad` (Phase 3 voice activity detection) ships
# as a C extension with no prebuilt wheel for linux/python3.11 on many
# platforms, so it compiles from source at install time and needs gcc.
# Rather than ship a compiler in the final image (bigger image, larger
# attack surface, slower deploys), compile in a throwaway "builder" stage
# and copy only the installed packages into the slim runtime image.

FROM python:3.11-slim AS builder

WORKDIR /app

# Build-time only: gcc to compile webrtcvad's C extension.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


FROM python:3.11-slim

WORKDIR /app

# Runtime only: curl for the healthcheck, ffmpeg for audio format
# conversion (browser-recorded webm/ogg -> normalized WAV for
# speech-to-text/VAD). No compiler here -- packages were already built.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

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
