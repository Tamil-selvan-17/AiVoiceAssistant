# Build context is the REPO ROOT, not backend/
# This image includes both backend/ and frontend/ and can be deployed
# as a single web service.

# ============================================================
# BUILDER STAGE
# ============================================================

FROM python:3.11-slim AS builder

WORKDIR /app

# Build-time dependencies.
# webrtcvad contains a native C extension and must be compiled
# when a compatible pre-built wheel is not available.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        g++ \
        python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Upgrade Python build tooling
RUN pip install --no-cache-dir --upgrade \
    pip \
    setuptools \
    wheel

# Copy Python dependencies
COPY backend/requirements.txt ./requirements.txt

# Install dependencies into /install.
# This directory will be copied into the runtime image.
RUN pip install \
    --no-cache-dir \
    --prefix=/install \
    -r requirements.txt


# ============================================================
# RUNTIME STAGE
# ============================================================

FROM python:3.11-slim

WORKDIR /app

# Runtime dependencies only.
#
# curl   -> Docker/PaaS healthcheck
# ffmpeg -> browser audio conversion
#
# No compiler is installed in the final image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy Python packages compiled in the builder stage
COPY --from=builder /install /usr/local

# ============================================================
# APPLICATION
# ============================================================

COPY backend/app ./app
COPY backend/pytest.ini ./pytest.ini
COPY frontend ./frontend

# ============================================================
# ENVIRONMENT
# ============================================================

ENV PYTHONUNBUFFERED=1
ENV FRONTEND_DIR=/app/frontend

EXPOSE 8000

# ============================================================
# HEALTHCHECK
# ============================================================

HEALTHCHECK \
    --interval=30s \
    --timeout=5s \
    --start-period=10s \
    --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/api/health || exit 1

# ============================================================
# START APPLICATION
# ============================================================

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]