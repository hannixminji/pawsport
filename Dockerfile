# --------- Builder Stage ---------
FROM ghcr.io/astral-sh/uv:0.10.0-python3.13-trixie-slim AS builder

# Set environment variables for uv
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

WORKDIR /app

# Install system packages needed to build psycopg2
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first (standard COPY, no BuildKit mount)
COPY uv.lock pyproject.toml ./
RUN uv sync --locked --no-install-project

# Copy the project source code
COPY . /app

# Install the project in non-editable mode
RUN uv sync --locked --no-editable

# --------- Final Stage ---------
FROM python:3.13.11-slim-trixie

# Create a non-root user for security
RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --shell /bin/bash --create-home app

# Copy the virtual environment from the builder stage
COPY --from=builder --chown=app:app /app/.venv /app/.venv

# Ensure the virtual environment is in the PATH
ENV PATH="/app/.venv/bin:$PATH"

# Set the working directory
WORKDIR /code

# Copy the project source code
COPY --chown=app:app src/app /code/app

# Copy startup script and fix Windows line endings (CRLF) AS ROOT
COPY start.sh /code/start.sh
RUN chmod +x /code/start.sh && sed -i 's/\r$//' /code/start.sh && chown app:app /code/start.sh

# Create directory for crudadmin with correct permissions
RUN mkdir -p /code/crudadmin_data && chown -R app:app /code/crudadmin_data

# Switch to the non-root user
USER app

# -------- Run both Worker and Web Server --------
CMD ["/code/start.sh"]
