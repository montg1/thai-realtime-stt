"""WebSocket ASR server backed by Typhoon ASR (NeMo FastConformer-Transducer).

Speaks the same wire protocol as example_browserclient/server.py so the existing
client.js works unchanged:
    inbound : [4-byte LE metadata length][metadata JSON][raw int16 PCM]
    outbound: {"type": "realtime"|"fullSentence", "text": ...}
"""
import asyncio
import json
import logging
import struct
import threading
import time
import warnings

warnings.filterwarnings("ignore")
logging.disable(logging.WARNING)

import numpy as np
import webrtcvad
import websockets
from scipy.signal import resample

PORT = 9002
SR = 16000                      # model sample rate
FRAME_MS = 30                   # webrtcvad accepts 10/20/30ms only
FRAME_LEN = SR * FRAME_MS // 1000
SILENCE_TO_FINALIZE = 0.7       # matches post_speech_silence_duration in rtstt
REALTIME_EVERY = 0.35           # how often to re-transcribe the growing buffer
MIN_SPEECH = 0.3                # ignore blips shorter than this
VAD_MODE = 2                    # matches webrtc_sensitivity in rtstt

print("Loading Typhoon ASR...", flush=True)
import nemo.collections.asr as nemo_asr

model = nemo_asr.models.ASRModel.from_pretrained(
    "scb10x/typhoon-asr-realtime", map_location="cuda")
model.eval()
_lock = threading.Lock()
print("Typhoon ASR ready", flush=True)


def transcribe(samples_i16):
    """int16 mono @16k -> text"""
    if len(samples_i16) < SR * 0.2:
        return ""
    audio = samples_i16.astype(np.float32) / 32768.0
    with _lock:
        out = model.transcribe(audio=[audio], batch_size=1, verbose=False)
    if not out:
        return ""
    h = out[0]
    return (h.text if hasattr(h, "text") else str(h)).strip()


class Session:
    """Per-connection VAD segmentation + transcription scheduling."""

    def __init__(self, send):
        self.send = send
        self.vad = webrtcvad.Vad(VAD_MODE)
        self.pending = np.zeros(0, dtype=np.int16)   # not yet framed
        self.speech = np.zeros(0, dtype=np.int16)    # current utterance
        self.in_speech = False
        self.silence_started = None
        self.last_realtime = 0.0
        self.last_sent = ""

    def feed(self, chunk_i16):
        self.pending = np.concatenate([self.pending, chunk_i16])
        while len(self.pending) >= FRAME_LEN:
            frame, self.pending = self.pending[:FRAME_LEN], self.pending[FRAME_LEN:]
            self._frame(frame)

    def _frame(self, frame):
        try:
            voiced = self.vad.is_speech(frame.tobytes(), SR)
        except Exception:
            voiced = False
        now = time.time()

        if voiced:
            self.in_speech = True
            self.silence_started = None
            self.speech = np.concatenate([self.speech, frame])
        elif self.in_speech:
            # keep trailing silence so the model hears the final consonant
            self.speech = np.concatenate([self.speech, frame])
            if self.silence_started is None:
                self.silence_started = now
            elif now - self.silence_started >= SILENCE_TO_FINALIZE:
                self._finalize()
                return

        if self.in_speech and now - self.last_realtime >= REALTIME_EVERY:
            self.last_realtime = now
            asyncio.get_event_loop().run_in_executor(None, self._emit_realtime)

    def _emit_realtime(self):
        buf = self.speech.copy()
        if len(buf) < SR * MIN_SPEECH:
            return
        text = transcribe(buf)
        if text and text != self.last_sent:
            self.last_sent = text
            self.send({"type": "realtime", "text": text})

    def _finalize(self):
        buf, self.speech = self.speech, np.zeros(0, dtype=np.int16)
        self.in_speech = False
        self.silence_started = None
        self.last_sent = ""
        if len(buf) < SR * MIN_SPEECH:
            return
        asyncio.get_event_loop().run_in_executor(
            None, lambda: self._emit_final(buf))

    def _emit_final(self, buf):
        text = transcribe(buf)
        if text:
            print(f"Sentence: {text}", flush=True)
            self.send({"type": "fullSentence", "text": text})


async def handler(ws, path=None):
    print("Client connected", flush=True)
    loop = asyncio.get_event_loop()
    queue = asyncio.Queue()

    def send(payload):
        loop.call_soon_threadsafe(queue.put_nowait, payload)

    async def pump():
        while True:
            item = await queue.get()
            try:
                await ws.send(json.dumps(item))
            except Exception:
                return

    pump_task = asyncio.ensure_future(pump())
    session = Session(send)
    try:
        async for message in ws:
            n = int.from_bytes(message[:4], "little")
            meta = json.loads(message[4:4 + n].decode("utf-8"))
            pcm = np.frombuffer(message[4 + n:], dtype=np.int16)
            src_sr = int(meta["sampleRate"])
            if src_sr != SR and len(pcm):
                pcm = resample(pcm, int(len(pcm) * SR / src_sr)).astype(np.int16)
            session.feed(pcm)
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        pump_task.cancel()
        print("Client disconnected", flush=True)


async def main():
    async with websockets.serve(handler, "0.0.0.0", PORT, max_size=None):
        print(f"Typhoon ASR server listening on ws://0.0.0.0:{PORT}", flush=True)
        await asyncio.Future()


asyncio.run(main())
