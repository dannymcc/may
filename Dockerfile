FROM python:3.12-slim

WORKDIR /app

# Install system dependencies including WeasyPrint requirements and gosu for privilege dropping.
# The upgrade pulls in Debian security fixes published since the base image was built (#419).
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    gir1.2-pango-1.0 \
    gir1.2-gdkpixbuf-2.0 \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Compile the translation catalogues. The .mo files are build artefacts rather
# than tracked files (#344), so the image builds them from the .po sources.
RUN pybabel compile -d app/translations

# Create non-root user and set up directories
RUN useradd --create-home --shell /bin/bash may \
    && mkdir -p /app/data/uploads \
    && chown -R may:may /app

# Copy and set up entrypoint
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Build args for version info
ARG GIT_SHA=""
ARG BUILD_DATE=""

# Labels for auto-update tools (Watchtower, etc.)
LABEL com.centurylinklabs.watchtower.enable="true"

# Set environment variables
ENV FLASK_APP=run.py
ENV PYTHONUNBUFFERED=1
ENV GIT_SHA=${GIT_SHA}
ENV BUILD_DATE=${BUILD_DATE}

# Expose port
EXPOSE 5050

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD gosu may python -c "import urllib.request; urllib.request.urlopen('http://localhost:5050/health')" || exit 1

# Use entrypoint to fix permissions then run as 'may' user
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:5050", "--workers", "2", "--threads", "4", "run:app"]
