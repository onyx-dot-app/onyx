FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi==0.115.4 "uvicorn[standard]==0.32.0"

COPY main.py .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "warning"]
