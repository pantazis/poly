FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy source code
COPY src/ ./src/
COPY config.yaml .

# Create logs directory
RUN mkdir -p /app/logs

# Run the trading bot
CMD ["python", "-m", "src.trading", "--config", "config.yaml"]
