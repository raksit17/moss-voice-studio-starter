FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py .
RUN useradd -u 10001 -m gateway
USER gateway
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8088", "--workers", "1"]
