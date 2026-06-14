FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY pyproject.toml README.md ./
COPY energy_router/ energy_router/
RUN pip install --no-cache-dir -e ".[dev]"

# Expose the API port
EXPOSE 8009

# Run the FastAPI server
CMD ["uvicorn", "energy_router.api:app", "--host", "0.0.0.0", "--port", "8009"]
