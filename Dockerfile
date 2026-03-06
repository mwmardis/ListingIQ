FROM python:3.10-slim

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir .

EXPOSE 8000
CMD ["python", "-m", "listingiq.api.server"]
