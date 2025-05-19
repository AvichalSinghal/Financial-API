#!/bin/sh
# entrypoint.sh - RENDER DEBUGGING VERSION

echo "--- RENDER ENTRYPOINT DEBUG ---"
echo "Attempting to run whoami: $(whoami)"
echo "Shell is: $0"
echo "PORT variable from environment: ($PORT)"

APP_PORT_TEST=${PORT:-8000}
echo "APP_PORT_TEST after expansion: ($APP_PORT_TEST)"

# Create a file to see if script runs and vars are set
echo "PORT from env: ($PORT)" > /app/render_env_test.txt
echo "APP_PORT_TEST: ($APP_PORT_TEST)" >> /app/render_env_test.txt

echo "Intentionally not starting Uvicorn for this test."
echo "Check /app/render_env_test.txt if you can access the container filesystem or build artifacts."
echo "Exiting entrypoint debug script."
# exec uvicorn main:app --host 0.0.0.0 --port "$APP_PORT_TEST" # Commented out for now