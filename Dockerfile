FROM python:3.11-slim
WORKDIR /app
ENV PIP_DEFAULT_TIMEOUT=120
RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md ./
COPY src/work_rag_guardrails ./work_rag_guardrails
COPY config ./config
COPY kb ./kb
COPY policies ./policies
RUN pip install --no-cache-dir --default-timeout=120 -e .
EXPOSE 8200
CMD ["python", "-m", "work_rag_guardrails.api"]
