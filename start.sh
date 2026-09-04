#!/usr/bin/env bash
# Start the Thai RealtimeSTT server (GPU) + serve the browser client.
set -e
cd "$(dirname "$0")"
D="$(pwd -W 2>/dev/null || pwd)"

docker rm -f rtstt >/dev/null 2>&1 || true
docker run -d --name rtstt --gpus all -p 9001:9001 \
  -v rtstt-hf-cache:/root/.cache/huggingface \
  -v "$D/models:/models:ro" \
  -v "$D/example_browserclient/server.py:/app/example_browserclient/server.py:ro" \
  montg1/realtimestt:v1.0-GPU

echo "Waiting for models to load (first run downloads ~3GB)..."
until docker logs rtstt 2>&1 | grep -q "Server started"; do
  docker ps -q -f name=rtstt | grep -q . || { echo "FAILED:"; docker logs rtstt | tail -20; exit 1; }
  sleep 3
done
echo "STT server ready on ws://localhost:9001"
echo "Now open http://localhost:8000  (Ctrl+C to stop)"
cd example_browserclient && python -m http.server 8000
