FROM python:3.11.7-slim-bookworm

WORKDIR /app

RUN pip install --no-cache-dir "pydantic-core>=2.28.0" fastapi uvicorn

COPY ./main.py /app/main.py

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
