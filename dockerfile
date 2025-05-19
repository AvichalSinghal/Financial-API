# Start with an official Python base image
FROM python:3.13-slim
# Or choose a version compatible with your code, e.g., python:3.11-slim, python:3.12-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt .

# Install Python dependencies
# --no-cache-dir reduces image size
# --upgrade pip ensures you have the latest pip
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copy your application code into the container
COPY ./main.py .
COPY ./sec_data_processor.py .
# If you have other .py files or directories your app needs, COPY them too.
# Note: We generally DO NOT copy the .env file into the Docker image for security.
# Environment variables will be set on Render directly.

# Expose the port the app runs on (Uvicorn will run on this port inside the container)
# Render will provide a PORT environment variable, which Uvicorn should use.
# We don't strictly need EXPOSE for Render if we use the PORT env var, but it's good practice.
EXPOSE 8000 
# (Render often uses port 10000 for its internal routing to your service, 
# but your app inside Docker should listen on the port specified by Render's PORT env var,
# or a default like 8000/80 if PORT isn't set, which we'll handle in the CMD)

# Command to run your FastAPI application using Uvicorn
# Uvicorn needs to listen on 0.0.0.0 to be accessible from outside the container.
# The port should ideally be taken from the PORT environment variable provided by Render.
# If PORT is not set, default to 8000 (or any other port you chose for EXPOSE).
# Render automatically injects a PORT environment variable.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "${PORT:-8000}"]