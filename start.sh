#!/bin/bash

# Start the ARQ worker in the background
echo "🚀 Starting Worker..."
arq app.core.worker.settings.WorkerSettings &

# Start the Web Server (FastAPI)
echo "🚀 Starting Web Server..."
exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}
