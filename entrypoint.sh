#!/bin/sh
# entrypoint.sh - For running FastAPI with Uvicorn on Render

# Set the default port if PORT environment variable is not set or is empty.
# Render will provide the PORT environment variable.
APP_PORT=${PORT:-8000}

echo "INFO: Starting Uvicorn server."
echo "INFO: Listening on host 0.0.0.0 and port $APP_PORT"
echo "INFO: Application module: main:app"

# Start Uvicorn
# Use exec to replace the shell process with the Uvicorn process.
# This ensures Uvicorn properly handles signals from Render (like for stopping or restarting).
exec uvicorn main:app --host 0.0.0.0 --port "$APP_PORT"