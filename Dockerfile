# Multi-stage production container for HELIOS heavy ion linac orchestration

FROM python:3.11-slim as base

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    EPICS_BASE=/opt/epics-base \
    PATH="/opt/epics-base/bin/linux-x86_64:$PATH"

WORKDIR /app

# Install system dependencies, Wine for TRACK, and EPICS build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libreadline-dev \
    git \
    curl \
    wine \
    wine64 \
    && rm -rf /var/lib/apt/lists/*

# Copy python dependencies
COPY pyproject.toml README.md ./
COPY helios ./helios

# Install python package with production dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

EXPOSE 8000 5064 5065

# Default entrypoint starts the web dashboard and orchestrator event bus
CMD ["helios", "dashboard", "--host", "0.0.0.0", "--port", "8000"]
