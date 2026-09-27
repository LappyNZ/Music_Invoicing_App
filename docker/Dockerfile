# syntax=docker/dockerfile:1
FROM python:3.11-slim

# curl is for the healthcheck in the compose files. Every Python package installs from a ready-built
# wheel, so no compiler is needed.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # default port inside container
    PORT=8000

# Create non-root user
RUN useradd -m appuser
WORKDIR /app

# Copy requirements first for caching
COPY requirements.txt /tmp/requirements.txt
RUN pip install --only-binary=:all: -r /tmp/requirements.txt

# Copy app code
COPY app/ /app/

# Start script (detects Flask/FastAPI)
COPY start.sh /start.sh
RUN chmod +x /start.sh && chown -R appuser:appuser /app

# Which commit this image was built from (shown in the app's footer and at /version)
ARG GIT_SHA=dev
ENV APP_VERSION=$GIT_SHA

USER appuser

EXPOSE 8000
CMD ["/start.sh"]
