FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        openssl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./

# Bind explicit (8444), transparent HTTPS (8443), transparent HTTP (8081).
EXPOSE 8081 8443 8444

CMD ["python", "server.py"]
