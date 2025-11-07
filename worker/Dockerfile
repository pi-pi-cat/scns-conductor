# Worker Service Dockerfile
# Optimized for ARM/aarch64 (Kunpeng) architecture

FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install system dependencies including bash for script execution
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    postgresql-client \
    bash \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY core/ ./core/
COPY worker/ ./worker/
COPY app.properties .

# Create necessary directories
RUN mkdir -p /var/log/scns-conductor /var/scns-conductor/jobs /var/scns-conductor/scripts

# Run worker
CMD ["python", "-m", "worker.main"]

