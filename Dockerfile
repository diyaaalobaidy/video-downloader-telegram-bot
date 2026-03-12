FROM python:3.12-slim

# Install system dependencies: ffmpeg for audio/video processing, nodejs for yt-dlp
RUN rm -rf /var/lib/apt/lists/* && apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

RUN mkdir -p downloads

CMD ["python", "main.py"]
