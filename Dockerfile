FROM python:3.10-slim

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir .

EXPOSE 8000
CMD ["/bin/sh", "-c", "cd /app && python -m uvicorn listingiq.api.server:app --host 0.0.0.0 --port ${PORT:-8000}"]
