# Dockerfile for Trading Algorithm
FROM python:3.14-slim

WORKDIR /app

COPY requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y git && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

COPY . .

CMD ["python", "main.py"]
