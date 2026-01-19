FROM python:3.11-slim

WORKDIR /app

# Copy and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the proxy script
COPY proxy.py .

# Expose the proxy port
EXPOSE 8888

# Run the proxy
CMD ["python", "proxy.py"]
