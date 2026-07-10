FROM python:3.11-slim

WORKDIR /app

# Proxy for apt/pip (passed via docker compose build-args)
ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY
ENV http_proxy=${HTTP_PROXY} https_proxy=${HTTPS_PROXY} no_proxy=${NO_PROXY}

# System dependencies for OpenCV
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 libsm6 libxext6 libxrender-dev libgl1 ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY shared/ shared/
COPY sinks/ sinks/
COPY stream_monitor/ stream_monitor/
COPY cli.py service.py source_worker.py __init__.py __main__.py ./
RUN pip install --no-cache-dir ".[npu]"

COPY config/ config/

EXPOSE 8999

# Use the installed console script (validates the entry point resolves).
CMD ["videostream-analytics", "serve", "--config", "config/config.yaml"]
