FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
COPY src ./src
COPY brand ./brand
COPY config ./config
COPY inbox ./inbox
COPY scripts/docker-entrypoint.sh /docker-entrypoint.sh

RUN chmod +x /docker-entrypoint.sh \
    && pip install --no-cache-dir . \
    && pip install --no-cache-dir -U "yt-dlp>=2024.8.0"

ENV PROJECT_ROOT=/app
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["python", "-m", "src.pipeline"]
