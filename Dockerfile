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
RUN pip install --no-cache-dir \
        typhoon-asr==0.1.1 \
        nemo-toolkit==3.0.0 \
        torch==2.14.0 \
        torchaudio==2.11.0 \
        numpy==2.0.1 \
        scipy==1.13.0 \
        websockets==12.0 \
        webrtcvad==2.0.10

WORKDIR /app
COPY typhoon_server.py /app/

# Model weights (~450 MB) download on first run into this volume, not the image.
VOLUME ["/models"]
EXPOSE 9002

CMD ["python3", "/app/typhoon_server.py"]
