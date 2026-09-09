"""FastAPI ครอบ engine เดิม — WebSocket สำหรับสตรีมสด + REST สำหรับไฟล์ทั้งก้อน

ทำไมไม่ใช้ SSE รับเสียง: SSE เป็นทางเดียว server -> client เท่านั้น ไม่มีช่องส่งขึ้น
จึงรับสตรีมเสียงไม่ได้เลย ส่วน fetch + ReadableStream body ต้อง HTTP/2 กับ
duplex:"half" ซึ่งรองรับเฉพาะ Chromium — WebSocket จบในเส้นเดียวและได้ทุกเบราว์เซอร์

โหลดโมเดลครั้งเดียวตอน import (typhoon_server ทำให้แล้ว) ทุก connection ใช้ร่วมกัน
"""
import asyncio
import json
import subprocess
import tempfile
import time

import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from scipy.signal import resample

# import แล้วโมเดลถูกโหลดทันที (typhoon_server มี guard __main__ ไม่ให้สตาร์ท ws server)
import typhoon_server as engine

app = FastAPI(
    title="Thai Realtime STT",
    description="ถอดเสียงภาษาไทยแบบเรียลไทม์ พร้อมแยกผู้พูด",
    version=engine.VERSION,
)

SR = engine.SR


@app.get("/v1/health")
def health():
    return {"ok": True, "version": engine.VERSION,
            "model": engine.MODEL_ID, "diarize": engine.embedder is not None}


def _decode_to_pcm16k(data: bytes, filename: str) -> np.ndarray:
    """ไฟล์เสียงรูปแบบไหนก็ได้ -> int16 mono 16k ผ่าน ffmpeg ที่มีในอิมเมจอยู่แล้ว"""
    with tempfile.NamedTemporaryFile(suffix="_" + filename[-16:]) as src:
        src.write(data)
        src.flush()
        out = subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-i", src.name,
             "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
            capture_output=True)
    if out.returncode != 0:
        raise HTTPException(400, f"อ่านไฟล์เสียงไม่ได้: {out.stderr.decode()[:200]}")
    return np.frombuffer(out.stdout, dtype=np.int16)


@app.post("/v1/transcribe")
async def transcribe_file(file: UploadFile = File(...), diarize: bool = True):
    """อัปไฟล์ทั้งก้อน รอผลครั้งเดียว — เส้นทางที่ง่ายที่สุดสำหรับคนเรียก API

    ใช้ VAD/ตัดประโยค/แยกผู้พูดชุดเดียวกับสตรีมสด ผลจึงเทียบกันได้ตรง ๆ
    ป้อนเสียงรวดเดียวไม่ต้องหน่วงตามเวลาจริง เพราะไม่มีใครรอฟังอยู่
    """
    pcm = _decode_to_pcm16k(await file.read(), file.filename or "audio")
    if not len(pcm):
        raise HTTPException(400, "ไฟล์ไม่มีเสียง")

    out: list = []

    def run():
        # Session ตั้ง callback ผ่าน asyncio.get_event_loop() ซึ่งใน uvloop จะพังถ้า
        # เรียกจากเธรดที่ไม่มี loop ของตัวเอง จึงสร้าง loop ประจำเธรดนี้ขึ้นมา
        # และไม่ไปเบียดลูปหลักที่รับ request อื่นอยู่
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            session = engine.Session(out.append)
            step = 2048          # ก้อนเท่าที่เบราว์เซอร์ส่ง VAD จะได้เห็นลำดับเฟรมเหมือนกัน
            for i in range(0, len(pcm), step):
                session.feed(pcm[i:i + step])
            session.feed(np.zeros(int(SR * 1.5), dtype=np.int16))  # เงียบท้ายให้ VAD ปิดประโยค

            # ป้อนเสียงเสร็จเร็วมาก แต่งานถอดเสียงทุกประโยคเข้าคิวรอ lock เดียวกันอยู่
            # รอจนไม่มีผลใหม่เข้ามา QUIET วินาที แทนการเดาเวลาตายตัว
            # เพดานคิดจากความยาวเสียง เพราะเสียงยาวก็มีประโยคให้ถอดมากตามส่วน
            quiet, deadline = 2.5, time.time() + 30 + len(pcm) / SR
            last_n, last_change = len(out), time.time()
            while time.time() < deadline:
                time.sleep(0.25)
                if len(out) != last_n:
                    last_n, last_change = len(out), time.time()
                elif time.time() - last_change > quiet:
                    break
        finally:
            loop.close()

    await asyncio.get_event_loop().run_in_executor(None, run)

    # งานถอดแต่ละประโยครันขนานกันจึงเสร็จไม่เรียง เรียงตามตำแหน่งในเสียงก่อนส่งคืน
    sentences = sorted((m for m in out if m.get("type") == "fullSentence"),
                       key=lambda m: m.get("audio_ms") or 0)
    return {
        "version": engine.VERSION,
        "duration_sec": round(len(pcm) / SR, 2),
        "text": " ".join(s["text"] for s in sentences),
        "segments": [
            {"text": s["text"], "audio_ms": s.get("audio_ms"),
             **({"speaker": s["speaker"], "speaker_conf": s.get("speaker_conf")}
                if diarize and s.get("speaker") is not None else {})}
            for s in sentences
        ],
    }


@app.websocket("/v1/stream")
async def stream(ws: WebSocket):
    """สตรีมสด — โปรโตคอลเดิมทุกอย่าง client.js/prove.js ใช้ได้โดยไม่ต้องแก้

    ขาขึ้น : [4 ไบต์ int32 LE ความยาว metadata][metadata JSON][PCM int16 LE mono]
    ขาลง   : JSON {type: hello|realtime|fullSentence, ...}
    """
    await ws.accept()
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def send(payload):
        loop.call_soon_threadsafe(queue.put_nowait, payload)

    async def pump():
        while True:
            item = await queue.get()
            try:
                await ws.send_text(json.dumps(item))
            except Exception:
                return

    pump_task = asyncio.ensure_future(pump())
    send({"type": "hello", "version": engine.VERSION,
          "model": engine.MODEL_ID.split("/")[-1],
          "diarize": engine.embedder is not None})
    session = engine.Session(send)

    try:
        while True:
            msg = await ws.receive_bytes()
            n = int.from_bytes(msg[:4], "little")
            meta = json.loads(msg[4:4 + n].decode("utf-8"))
            pcm = np.frombuffer(msg[4 + n:], dtype=np.int16)
            src_sr = int(meta["sampleRate"])
            if src_sr != SR and len(pcm):
                pcm = resample(pcm, int(len(pcm) * SR / src_sr)).astype(np.int16)
            session.feed(pcm)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        pump_task.cancel()
