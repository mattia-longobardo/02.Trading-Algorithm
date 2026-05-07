# Dockerfile for Trading Algorithm
FROM python:3.14-slim

WORKDIR /app

# bcrypt's wheel covers cpython 3.14 on linux/amd64 already, but git is still
# needed for the toon-format VCS dependency. Build deps for bcrypt are
# included in case the wheel is unavailable for the target platform.
COPY requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        build-essential \
        libffi-dev \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y git build-essential libffi-dev \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY . .

CMD ["python", "main.py"]
