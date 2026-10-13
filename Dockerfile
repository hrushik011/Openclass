# syntax=docker/dockerfile:1
FROM python:3.11-slim

WORKDIR /app

# Install system deps for cryptography / google libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app source
COPY app/ ./app/
COPY frontend/ ./frontend/
COPY data/ ./data/

# Create upload dirs
RUN mkdir -p /app/uploads/submissions /app/uploads/assignments

# Expose port (Railway overrides this with $PORT)
EXPOSE 8000

# Start FastAPI
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
