# Start with an official Python base image
FROM python:3.13-slim
# Or your chosen Python version

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copy your application code AND the entrypoint script
COPY ./main.py .
COPY ./sec_data_processor.py .
COPY ./entrypoint.sh .

# Make the entrypoint script executable INSIDE the container
RUN chmod +x ./entrypoint.sh

# Expose the default port (good practice, though PORT env var will be used)
EXPOSE 8000

# Set the entrypoint to run your script
ENTRYPOINT ["./entrypoint.sh"]
# We don't need a CMD here, as the entrypoint script handles running Uvicorn.