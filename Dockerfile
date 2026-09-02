# Guardrails Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

# Copy application code + KB wordlists
COPY src/ ./src/
COPY config/ ./config/
COPY kb/ ./kb/
COPY .env.example .env

# Expose port
EXPOSE 8200

# Run the service
CMD ["python", "-m", "work_rag_guardrails.api"]