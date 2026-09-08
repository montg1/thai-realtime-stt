"""WebSocket ASR server backed by Typhoon ASR (NeMo FastConformer-Transducer).

Speaks the same wire protocol as example_browserclient/server.py so the existing
client.js works unchanged:
    inbound : [4-byte LE metadata length][metadata JSON][raw int16 PCM]
    outbound: {"type": "realtime"|"fullSentence", "text": ...}
"""
import asyncio
import json
import logging
import os
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

# ตั้งผ่าน env ได้ เพื่อรันหลายโมเดลพร้อมกันคนละพอร์ตแล้วเทียบกันตรง ๆ
# โมเดลอื่นที่ลองได้: nectec/Pathumma-stt-th-fastconformer-rnnt-large (RNNT เหมือนกัน)
# ชื่อเดิม scb10x/typhoon-asr-realtime ยังเข้าได้แต่เป็น redirect 307 ของ repo ที่ย้ายแล้ว
MODEL_ID = os.environ.get("ASR_MODEL", "typhoon-ai/typhoon-asr-realtime")
PORT = int(os.environ.get("ASR_PORT", "9002"))
SR = 16000                      # model sample rate
FRAME_MS = 30                   # webrtcvad accepts 10/20/30ms only
FRAME_LEN = SR * FRAME_MS // 1000
SILENCE_TO_FINALIZE = 0.7       # matches post_speech_silence_duration in rtstt
REALTIME_EVERY = 0.35           # how often to re-transcribe the growing buffer
MIN_SPEECH = 0.3                # ignore blips shorter than this
# วงสนทนาหลายคนไม่มีช่วงเงียบยาวพอให้ SILENCE_TO_FINALIZE ทำงาน ประโยคจึงไม่ปิดเลย
# (วัดแล้ว: คลิปคุยในร้าน 5 นาที ได้ประโยคเดียว) ต้องมีเพดานบังคับตัด ไม่งั้นทั้ง ASR
# และ diarization ได้ก้อนใหญ่ก้อนเดียวจนไร้ประโยชน์
MAX_SEGMENT = float(os.environ.get("MAX_SEGMENT", "5.0"))
# ตัดด้วยเพดานเวลาคือตัดตรงไหนก็ตัด คำที่คร่อมรอยตัดจะขาดครึ่งทั้งสองฝั่ง
# (วัดแล้ว: คลิปโหนกระแส 32 จาก 36 ประโยคถูกตัดด้วยเพดาน ไม่ใช่ด้วย VAD)
# ยกท้ายประโยคก่อนหน้าไปเป็นต้นประโยคถัดไป คำที่คร่อมรอยตัดจะครบอย่างน้อยหนึ่งฝั่ง
# ยอมให้ซ้ำดีกว่ายอมให้หาย
SEG_OVERLAP = float(os.environ.get("SEG_OVERLAP", "0.6"))
# hop กับความยาวหน้าต่างคุมคนละอย่าง: hop คุมความละเอียดของไทม์ไลน์ผู้พูด
# ส่วนความยาวหน้าต่างคุมคุณภาพ embedding (วัดแล้ว 3s แยกคนดีกว่า 1.5s ชัดเจน)
# Utterr ผูกไว้ที่ 1.0s/0.1s เราแยกสองค่าออกจากกันเพื่อเอาข้อดีทั้งคู่
EMB_EVERY = float(os.environ.get("DIAR_HOP", "0.25"))   # ถี่แค่ไหนถึงจะสกัด embedding
# ตัดประโยคตอนเปลี่ยนคนพูด ไม่ใช่รอแต่ความเงียบ — คนพูดสลับไว ๆ ไม่มีช่วงเงียบให้รอ
# ต้องเห็นคนใหม่ติดกันกี่หน้าต่างถึงจะเชื่อว่าเปลี่ยนจริง ไม่ใช่ embedding แกว่งชั่วครู่
CHANGE_WINDOWS = int(os.environ.get("DIAR_CHANGE_WIN", "3"))
# ประโยคต้องยาวพอควรก่อนถึงยอมให้ตัด ไม่งั้นจะแตกเป็นเศษสั้น ๆ จน ASR ถอดไม่ได้เรื่อง
CHANGE_MIN_SEC = float(os.environ.get("DIAR_CHANGE_MIN", "1.2"))
VAD_MODE = 2                    # matches webrtc_sensitivity in rtstt
# webrtcvad ตัดสินจากพลังงานในย่านความถี่ ซึ่งมองว่าดนตรีประกอบเป็นเสียงพูด
# ทำให้คลิปที่มี BGM ถูกมองว่าพูดต่อเนื่องทั้งคลิป ประโยคเดียวยาวหลายสิบวินาที
# silero เป็นโมเดลนิวรัลที่แยกเสียงพูดจากเสียงอื่นได้ จึงเป็นค่าเริ่มต้น
VAD_KIND = os.environ.get("VAD", "silero")
SILERO_THRESH = float(os.environ.get("VAD_THRESH", "0.5"))
FRAME_LEN = 512 if VAD_KIND == "silero" else FRAME_LEN   # silero v6 รับ 512 ตัวอย่างเป๊ะที่ 16k

print(f"Loading ASR: {MODEL_ID}", flush=True)
import nemo.collections.asr as nemo_asr

# repo บางตัว (เช่น nectec/Pathumma-stt-th-fastconformer-rnnt-large) มีแต่ไฟล์ .nemo
# ซึ่ง from_pretrained อ่านไม่ได้ เพราะมันมองหา model_config.yaml ที่ระดับ repo
# .nemo เป็น tar ที่ห่อ config กับ weight ไว้ข้างในอยู่แล้ว ต้องเข้าทาง restore_from
if MODEL_ID.endswith(".nemo"):
    model = nemo_asr.models.ASRModel.restore_from(MODEL_ID, map_location="cuda")
else:
    model = nemo_asr.models.ASRModel.from_pretrained(MODEL_ID, map_location="cuda")
model.eval()
_lock = threading.Lock()

# ปิดไว้เป็นค่าเริ่มต้น — โหลด TitaNet เพิ่มอีก ~0.4 GB และเพิ่มงานต่อประโยค
embedder = None
if os.environ.get("DIARIZE", "0") == "1":
    import diarize
    print("Loading TitaNet (diarization)...", flush=True)
    embedder = diarize.Embedder()
    print("diarization on", flush=True)

_silero = None
if VAD_KIND == "silero":
    import torch
    _silero, _ = torch.hub.load("snakers4/silero-vad", "silero_vad", trust_repo=True)
    _silero.eval()
    _vad_lock = threading.Lock()
    print("VAD: silero", flush=True)
else:
    print(f"VAD: webrtcvad mode {VAD_MODE}", flush=True)

# พิมพ์ค่าที่ใช้จริงทุกครั้ง เพราะไฟล์ถูก bind mount เข้ามาและมี __pycache__ ค้างได้
# ถ้าตัวเลขไม่ตรงกับที่แก้ล่าสุด แปลว่ากำลังรันโค้ดเก่าอยู่ ไม่ต้องเดา
_cfg = dict(vad=VAD_KIND, max_segment=MAX_SEGMENT, overlap=SEG_OVERLAP,
            silence=SILENCE_TO_FINALIZE)
if embedder:
    _cfg.update(emb=embedder.kind, hop=EMB_EVERY, window=diarize.WINDOW_SEC,
                change_win=CHANGE_WINDOWS, change_min=CHANGE_MIN_SEC,
                same=diarize.SAME_SPEAKER, weak=diarize.WEAK_MATCH,
                cohesive=diarize.COHESIVE, min_cluster=diarize.MIN_CLUSTER,
                min_seg=diarize.MIN_SEG_SEC, max_emb=diarize.MAX_EMB_PER_SPK,
                max_pending=diarize.MAX_PENDING)
print("CONFIG " + "  ".join(f"{k}={v}" for k, v in _cfg.items()), flush=True)
print(f"ASR ready on :{PORT}", flush=True)


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
        self.vad = None if VAD_KIND == "silero" else webrtcvad.Vad(VAD_MODE)
        self.pending = np.zeros(0, dtype=np.int16)   # not yet framed
        self.speech = np.zeros(0, dtype=np.int16)    # current utterance
        # แยกบัฟเฟอร์ที่มีแต่เฟรมซึ่ง VAD บอกว่าเป็นเสียงพูด ไว้ป้อน embedding อย่างเดียว
        # self.speech เก็บความเงียบท้ายประโยคไว้ด้วยเพื่อให้ ASR ได้ยินพยัญชนะสะกด
        # แต่ความเงียบนั้นไปเจือจาง embedding ผู้พูดจนแยกคนได้แย่ลง
        self.voiced = np.zeros(0, dtype=np.int16)
        self.in_speech = False
        self.silence_started = None
        self.last_realtime = 0.0
        self.last_sent = ""
        # ผู้พูดสะสมต่อการเชื่อมต่อ ไม่ใช่ต่อทั้งเซิร์ฟเวอร์ คนละห้องประชุมจะได้ไม่ปนกัน
        self.spk = diarize.SpeakerHandler() if embedder else None
        self.spk_votes = []          # ผู้พูดที่ทายได้จากแต่ละหน้าต่างในประโยคนี้
        self.recent = []             # ผู้พูดของหน้าต่างล่าสุด ใช้ดูว่าเปลี่ยนคนหรือยัง
        self.want_cut = False        # ตั้งจากเธรด embedding ให้ลูปหลักมาตัดให้
        self.last_emb = 0.0
        # นับเสียงที่รับเข้ามาแล้วเป็นตัวอย่าง ใช้บอกฝั่ง client ว่าผลลัพธ์นี้เป็นของ
        # เสียงถึงวินาทีไหน จะได้วัด lag จากเวลาในสตรีมจริง ไม่ใช่จากนาฬิกาเบราว์เซอร์
        self.consumed = 0

    def feed(self, chunk_i16):
        self.consumed += len(chunk_i16)
        self.pending = np.concatenate([self.pending, chunk_i16])
        while len(self.pending) >= FRAME_LEN:
            frame, self.pending = self.pending[:FRAME_LEN], self.pending[FRAME_LEN:]
            self._frame(frame)

    def _frame(self, frame):
        try:
            if self.vad is None:
                import torch
                with _vad_lock, torch.no_grad():
                    t = torch.from_numpy(frame.astype(np.float32) / 32768.0)
                    voiced = _silero(t, SR).item() >= SILERO_THRESH
            else:
                voiced = self.vad.is_speech(frame.tobytes(), SR)
        except Exception:
            voiced = False
        now = time.time()

        if voiced:
            self.in_speech = True
            self.silence_started = None
            self.speech = np.concatenate([self.speech, frame])
            self.voiced = np.concatenate([self.voiced, frame])
            if self.want_cut or len(self.speech) >= SR * MAX_SEGMENT:
                self.want_cut = False
                self._finalize(overlap=True)
                return
        elif self.in_speech:
            # keep trailing silence so the model hears the final consonant
            self.speech = np.concatenate([self.speech, frame])
            if self.silence_started is None:
                self.silence_started = now
            elif now - self.silence_started >= SILENCE_TO_FINALIZE:
                self._finalize()
                return

        if self.in_speech and self.spk is not None and now - self.last_emb >= EMB_EVERY:
            self.last_emb = now
            win = self.voiced[-int(SR * diarize.WINDOW_SEC):].copy()
            asyncio.get_event_loop().run_in_executor(None, self._emit_embedding, win)

        if self.in_speech and now - self.last_realtime >= REALTIME_EVERY:
            self.last_realtime = now
            asyncio.get_event_loop().run_in_executor(None, self._emit_realtime)

    def _emit_embedding(self, win):
        """จัดกลุ่มผู้พูดจากหน้าต่างสั้น ๆ ระหว่างที่ยังพูดอยู่

        ทำที่ระดับหน้าต่างไม่ใช่ระดับประโยค เพราะกอง pending ต้องสะสมให้ถึง MIN_CLUSTER
        ก่อนจะตั้งผู้พูดใหม่ได้ ถ้าเก็บประโยคละชิ้นกว่าจะครบก็ผ่านไปหลายนาที
        และประโยคเดียวอาจยาวเป็นสิบวินาทีจนมีหลายคนพูดอยู่ข้างใน
        """
        sid, _ = self.spk.classify(embedder(win))
        if sid is None:
            return
        self.spk_votes.append(sid)

        self.recent.append(sid)
        del self.recent[:-CHANGE_WINDOWS]
        if len(self.recent) < CHANGE_WINDOWS or len(set(self.recent)) != 1:
            return
        # หน้าต่างล่าสุดเห็นคนเดียวกันติดกันครบแล้ว ถ้าไม่ใช่คนที่ครองประโยคนี้อยู่
        # แปลว่าเปลี่ยนคนพูดจริง สั่งให้ตัดประโยค ณ จุดนี้
        earlier = self.spk_votes[:-CHANGE_WINDOWS]
        if earlier and max(set(earlier), key=earlier.count) != sid \
                and len(self.voiced) >= SR * CHANGE_MIN_SEC:
            self.want_cut = True

    def _emit_realtime(self):
        buf = self.speech.copy()
        if len(buf) < SR * MIN_SPEECH:
            return
        at = self.consumed
        text = transcribe(buf)
        if text and text != self.last_sent:
            self.last_sent = text
            self.send({"type": "realtime", "text": text,
                       "audio_ms": at * 1000 // SR})

    def _finalize(self, overlap=False):
        buf = self.speech
        tail = buf[-int(SR * SEG_OVERLAP):] if overlap else np.zeros(0, dtype=np.int16)
        self.speech = tail.copy()
        self.voiced = tail.copy() if overlap else np.zeros(0, dtype=np.int16)
        self.in_speech = overlap        # ตัดด้วยเพดาน = ยังพูดอยู่ ไม่ต้องรอเริ่มใหม่
        self.silence_started = None
        self.last_sent = ""
        if len(buf) < SR * MIN_SPEECH:
            return
        seg_end = self.consumed
        asyncio.get_event_loop().run_in_executor(
            None, lambda: self._emit_final(buf, seg_end))

    def _emit_final(self, buf, seg_end=0):
        text = transcribe(buf)
        if not text:
            return
        # seg_end = ตำแหน่งในสตรีมที่ประโยคนี้จบ client เอาไปลบกับเสียงที่ส่งไปแล้ว
        # ได้ lag จริงว่า "พูดจบไปแล้วกี่มิลลิวินาทีถึงเห็นข้อความ"
        msg = {"type": "fullSentence", "text": text,
               "audio_ms": seg_end * 1000 // SR}
        if self.spk is not None:
            # ผู้พูดของประโยค = เสียงข้างมากของหน้าต่างย่อยทั้งหมดในประโยคนั้น
            # ประโยคที่มีหลายคนพูดคาบกันจะได้แค่คนที่พูดมากที่สุด แยกละเอียดกว่านี้
            # ต้องมี word timestamp มาจับคู่กับ timeline ของผู้พูด
            votes, self.spk_votes = self.spk_votes, []
            self.recent = []
            if votes:
                sid = max(set(votes), key=votes.count)
                msg["speaker"] = sid
                msg["speaker_conf"] = round(votes.count(sid) / len(votes), 3)
                msg["speaker_windows"] = len(votes)
        print(f"Sentence[{msg.get('speaker')}]: {text}", flush=True)
        self.send(msg)


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
