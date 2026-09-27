# syntax=docker/dockerfile:1
FROM python:3.11-slim

# Install system libs – add more if your app needs them (wkhtmltopdf, cairo, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# OPTIONAL: If you generate PDFs with wkhtmltopdf or WeasyPrint, uncomment what you need:
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     wkhtmltopdf \
#     libffi-dev libpango-1.0-0 libpangoft2-1.0-0 libjpeg62-turbo \
#     && rm -rf /var/lib/apt/lists/*

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
RUN pip install --upgrade pip && pip install -r /tmp/requirements.txt \
    && pip install gunicorn 

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
