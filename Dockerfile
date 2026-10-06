# SwingGrade server image (used by Railway; also runs anywhere Docker does).
#   docker build -t swinggrade .
#   docker run -p 8000:8000 -e MODAL_TOKEN_ID=... -e MODAL_TOKEN_SECRET=... swinggrade
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
# ffmpeg: video decode; libgl1/libglib: OpenCV (pulled in by rtmlib)
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg curl ca-certificates libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Browser pose model (served from this app so phones don't depend on a CDN)
# and the RTMPose ONNX models for the CPU fallback, baked into the image.
RUN sh tools/fetch_models.sh

ENV SG_WORK_DIR=/app/work
EXPOSE 8000
# Railway injects $PORT. One worker: upload jobs live in this process's memory.
CMD ["sh", "-c", "exec uvicorn swinggrade.app:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
