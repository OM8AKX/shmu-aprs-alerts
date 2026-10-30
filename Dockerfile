# SHMÚ → APRS Alerts – Docker image
FROM python:3.12-slim

LABEL org.opencontainers.image.title="SHMÚ APRS Alerts"
LABEL org.opencontainers.image.description="Meteorologické výstrahy SHMÚ → APRS-IS"
LABEL org.opencontainers.image.source="https://github.com/OM8AKX/shmu-aprs-alerts"

# System deps for lxml
RUN apt-get update && apt-get install -y --no-install-recommends \
        libxml2 \
        libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first (better layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application
COPY main.py .
COPY shmu_aprs/ ./shmu_aprs/
COPY config/config.example.yaml ./config/config.example.yaml

# Non-root user
RUN useradd -r -u 1000 -d /app -s /usr/sbin/nologin aprs \
    && mkdir -p /app/config /var/log \
    && chown -R aprs:aprs /app /var/log

USER aprs

ENV PYTHONUNBUFFERED=1 \
    SHMU_APRS_CONFIG=/app/config/config.yaml

# Default: run service (override with --once for one-shot test)
ENTRYPOINT ["python", "main.py"]
CMD ["--config", "/app/config/config.yaml"]
