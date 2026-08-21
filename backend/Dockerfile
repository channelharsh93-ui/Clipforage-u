FROM python:3.12-slim

# ffmpeg + OpenCV runtime deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-minimal.txt ./
# Use requirements.txt (includes faster-whisper for real captions).
# Swap to requirements-minimal.txt if you want a smaller image without local transcription.
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN mkdir -p /app/storage/projects /app/storage/library/music /app/storage/library/sfx /app/storage/library/logos

ENV STORAGE_ROOT=/app/storage \
    DATABASE_PATH=/app/storage/viral_clips.sqlite3 \
    PYTHONUNBUFFERED=1

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
