# Typhoon ASR realtime — Thai streaming speech-to-text over WebSocket.
#
# Built on python:3.10-slim rather than an nvidia/cuda base: modern torch
# wheels ship their own CUDA runtime, so an OS-level CUDA layer would only
# duplicate it. The image this replaces (docker commit over a CUDA 12.3
# base, then pip pulling a CUDA 13 torch) carried both and cost 42.3 GB.

FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models

# libsndfile1 + ffmpeg: soundfile/lhotse audio I/O. git: some NeMo extras
# resolve their metadata through it at import time.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libsndfile1 ffmpeg git \
    && rm -rf /var/lib/apt/lists/*

# Versions pinned to the set verified working on an RTX 3070 (driver 591.86).
# pyannote.audio ต้องเป็น 4.x — 3.3.2 เรียก torchaudio.AudioMetaData ซึ่งถูกถอด
# ออกไปแล้วใน torchaudio 2.11 ใช้สำหรับโมเดล speaker embedding ของ diarize.py
RUN pip install --no-cache-dir \
        typhoon-asr==0.1.1 \
        nemo-toolkit==3.0.0 \
        torch==2.14.0 \
        torchaudio==2.11.0 \
        numpy==2.0.1 \
        scipy==1.13.0 \
        websockets==12.0

# แยกเป็นอีก layer โดยตั้งใจ ถ้ารวมไว้ในคำสั่งเดียวข้างบน resolver จะต้องหาทางที่
# สอดคล้องกับทุก pin พร้อมกันแล้วแก้ไม่ได้ ลงทีหลังมันจะยึดของที่ติดตั้งแล้วเป็นฐาน
RUN pip install --no-cache-dir "pyannote.audio==4.0.7"

# FastAPI ครอบ engine เดิม — แยก layer เหมือน pyannote ด้วยเหตุผลเดียวกัน
RUN pip install --no-cache-dir \
        "fastapi==0.115.6" "uvicorn[standard]==0.34.0" "python-multipart==0.0.20"

WORKDIR /app
COPY typhoon_server.py diarize.py version.json /app/
COPY api /app/api

# Model weights (~450 MB) download on first run into this volume, not the image.
VOLUME ["/models"]
EXPOSE 8000

# ค่าเริ่มต้นเป็น API ตัวเดิมยังรันได้ด้วย: python3 /app/typhoon_server.py
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "/app"]
