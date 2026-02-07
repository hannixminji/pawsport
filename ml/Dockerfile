# Use Python 3.12.12 slim (Debian Trixie)
FROM python:3.12.12-slim-trixie

# Create a non-root user for security
RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --shell /bin/bash --create-home app

# Set working directory
WORKDIR /app

# Prevent Python from writing .pyc files & using stdout buffering
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies required by onnxruntime, opencv, Pillow
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libgl1 \
        libglib2.0-0 \
        libjpeg62-turbo \
        python3-dev \
        zlib1g \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency list
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the ML service source code
COPY --chown=app:app . .

# Switch to non-root user
USER app

# Start FastAPI on port 8080 (Cloud Run default)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
