FROM python:3.11-slim

WORKDIR /app

# Copy dependencies file first
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Copy all source files into the container
COPY . .

ENV PYTHONUNBUFFERED=1

EXPOSE 8080

CMD ["uvicorn","main:app","--host","0.0.0.0","--port","8080"]
