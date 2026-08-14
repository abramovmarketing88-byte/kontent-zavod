FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
COPY src ./src
COPY brand ./brand
COPY config ./config
COPY inbox ./inbox

RUN pip install --no-cache-dir .

ENV PROJECT_ROOT=/app
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "src.pipeline"]
