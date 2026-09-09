"""Speaker diarization แบบ online สำหรับสตรีมเสียงสด

ตรรกะจัดกลุ่มผู้พูดยกมาจาก Utterr (github.com/maximus-choi/Utterr) เฉพาะคลาส
SpeakerHandler ตัดส่วนที่ผูกกับ PyQt และ soundcard ออก ของเดิมทำงานบน Windows
ผ่าน loopback + GUI ส่วนที่นี่รับ numpy array จาก websocket โดยตรง

ตัวสกัด embedding ใช้ pyannote WeSpeaker ResNet34-LM ตามต้นฉบับ
"""
import os
import threading

import numpy as np

SR = 16000

# ค่า default ตรงกับของ Utterr เพราะจูนมากับ WeSpeaker เหมือนกัน และเป็นชุดที่ทดสอบจริง
#
# ความยาวหน้าต่าง วัดบนคลิปทีวีไทย 3 นาที (cos ในกลุ่ม / ข้ามกลุ่ม / แบ่ง k=2 ได้):
#   1.5s   0.264 0.082  176/3   <- สั้นไป แยกไม่ออก
#   3.0s   0.434 0.170  152/25  <- ใช้ค่านี้
#   5.0s   0.520 0.218  149/26
#
# หน้าต่างยาวขึ้น embedding นิ่งขึ้น แต่จับการสลับผู้พูดได้ช้าลง 3.0s เป็นจุดที่พอดี
# ทุกค่าปรับผ่าน env ได้ เพราะขึ้นกับไมค์ ห้อง และเสียงรบกวนของงานจริง
SAME_SPEAKER = float(os.environ.get("DIAR_SAME", "0.40"))
WEAK_MATCH = float(os.environ.get("DIAR_WEAK", "0.30"))
COHESIVE = float(os.environ.get("DIAR_COHESIVE", "0.60"))
MIN_CLUSTER = int(os.environ.get("DIAR_MIN_CLUSTER", "8"))
WINDOW_SEC = float(os.environ.get("DIAR_WINDOW", "3.0"))
MAX_SPEAKERS = 10
# จำกัดจำนวน embedding ต่อคน ไม่งั้นคนที่พูดก่อนสะสมเป็นร้อยชิ้นจน centroid นิ่งและ
# กว้างจนกลืนคนที่เข้ามาทีหลัง เก็บเฉพาะช่วงหลังทำให้ centroid ขยับตามเสียงปัจจุบัน
MAX_EMB_PER_SPK = int(os.environ.get("DIAR_MAX_EMB", "40"))
# กอง pending ที่ค้างนานจะมีแต่เศษเสียงคละกันจนหากลุ่มเกาะกันไม่เจอ ตัดของเก่าทิ้ง
MAX_PENDING = int(os.environ.get("DIAR_MAX_PENDING", "60"))
# บทพูดสั้น (ตัวอย่างหนัง บทสนทนาโต้ตอบเร็ว) มีเสียงพูดไม่ถึงค่านี้ จะไม่ถูก embed เลย
# แล้วประโยคนั้นจะได้ speaker=None ตลอด ตั้งสูงได้ embedding นิ่งขึ้นแต่เสียประโยคสั้นไป
MIN_SEG_SEC = float(os.environ.get("DIAR_MIN_SEG", "0.8"))


class Embedder:
    """เสียงหนึ่งช่วง -> เวกเตอร์ลักษณะเฉพาะของผู้พูด

    WeSpeaker ResNet34-LM เทรนด้วย large-margin finetuning มาเพื่อให้ระยะห่างระหว่าง
    คนกว้าง ซึ่งเป็นสิ่งที่ clustering ต้องการโดยตรง
    """
    kind = "wespeaker"

    def __init__(self, device="cuda"):
        import torch
        from pyannote.audio import Model
        self.torch = torch
        self.device = device
        self.lock = threading.Lock()
        self.model = Model.from_pretrained("pyannote/wespeaker-voxceleb-resnet34-LM")
        self.model = self.model.to(torch.device(device)).eval()

    def __call__(self, samples_i16):
        if len(samples_i16) < SR * MIN_SEG_SEC:
            return None
        audio = samples_i16.astype(np.float32) / 32768.0
        with self.lock, self.torch.no_grad():
            t = self.torch.tensor(audio).unsqueeze(0).to(self.device)
            emb = self.model(t.unsqueeze(0))   # (batch, channel, sample)
        return emb.squeeze().cpu().numpy()


class SpeakerHandler:
    """จับคู่ embedding เข้ากับผู้พูด และตั้งผู้พูดใหม่เมื่อมีหลักฐานพอ

    เสียงที่ไม่เหมือนใครเลยจะยังไม่ถูกตั้งเป็นคนใหม่ทันที แต่เข้ากอง pending ก่อน
    รอจนมีสมาชิกพอและเกาะกลุ่มกันจริงถึงค่อยเลื่อนขั้น กันไม่ให้เสียงรบกวนชิ้นเดียว
    กลายเป็นผู้พูดคนใหม่ — นี่คือแก่นของ Utterr
    """

    def __init__(self, max_speakers=MAX_SPEAKERS):
        self.max_speakers = max_speakers
        self.centroids = {}          # spk_id -> เวกเตอร์กลางของคนนั้น
        self.embs = {}               # spk_id -> embedding ทุกชิ้นที่เคยเจอ
        self.pending = []            # embedding ที่ยังไม่รู้ว่าเป็นใคร
        self.pending_open = True

    def _cos(self, emb):
        ids = [i for i, c in self.centroids.items() if c is not None]
        if not ids:
            return None, 0.0
        m = np.array([self.centroids[i] for i in ids])
        m = m / np.linalg.norm(m, axis=1, keepdims=True)
        sims = m @ (emb / np.linalg.norm(emb))
        j = int(np.argmax(sims))
        return ids[j], float(sims[j])

    def _new_speaker(self, embs):
        sid = max(self.centroids, default=-1) + 1
        self.embs[sid] = list(embs)[-MAX_EMB_PER_SPK:]
        self.centroids[sid] = np.median(embs, axis=0)
        if len(self.centroids) >= self.max_speakers:
            self.pending_open = False
        return sid

    def _promote(self):
        """หาช่วงต่อเนื่องในกอง pending ที่เกาะกลุ่มกันพอจะเป็นคนหนึ่งคน"""
        if len(self.pending) < MIN_CLUSTER or not self.pending_open:
            return None
        arr = np.array(self.pending)
        arr = arr / np.linalg.norm(arr, axis=1, keepdims=True)
        # ไล่จากกลุ่มใหญ่ไปเล็ก เอากลุ่มแรกที่ทุกคู่ห่างกันไม่เกิน COHESIVE
        for size in range(len(arr), MIN_CLUSTER - 1, -1):
            for start in range(0, len(arr) - size + 1):
                block = arr[start:start + size]
                if (1 - block @ block.T).max() <= COHESIVE:
                    sid = self._new_speaker(self.pending[start:start + size])
                    del self.pending[start:start + size]
                    return sid
        return None

    def classify(self, emb):
        """คืน (speaker_id, ความมั่นใจ) — speaker_id เป็น None ถ้ายังตัดสินไม่ได้"""
        if emb is None:
            return None, 0.0

        sid, sim = self._cos(emb)

        if sid is not None and sim >= SAME_SPEAKER:
            self.embs[sid].append(emb)
            del self.embs[sid][:-MAX_EMB_PER_SPK]
            self.centroids[sid] = np.median(self.embs[sid], axis=0)
            return sid, sim

        if not self.pending_open:
            return sid, sim          # เต็มโควตาผู้พูดแล้ว ยัดเข้าคนที่ใกล้สุด

        # ทุกชิ้นที่ไม่เข้าเกณฑ์ "คนเดิมชัดเจน" ต้องเข้ากอง pending เสมอ แม้จะพอเข้าเค้า
        # กับใครอยู่บ้าง ของเดิมคืนคนเดิมแล้วทิ้งชิ้นนั้นไปเลย ทำให้คนที่เข้ามาทีหลัง
        # ถูกกลืนเข้าคนเก่าตลอดและไม่มีวันสะสมหลักฐานพอจะตั้งเป็นคนใหม่
        self.pending.append(emb)
        del self.pending[:-MAX_PENDING]
        promoted = self._promote()
        if promoted is not None:
            return promoted, sim
        # ยังตั้งคนใหม่ไม่ได้ ถ้าพอเข้าเค้ากับใครอยู่ก็แสดงคนนั้นไปก่อน จอจะได้ไม่กระพริบ
        if sid is not None and sim >= WEAK_MATCH:
            return sid, sim
        return None, sim

    def stats(self):
        return {"speakers": len(self.centroids), "pending": len(self.pending)}


def demo():
    """เช็คว่าตรรกะแยกคนได้จริง ด้วย embedding สังเคราะห์สองกลุ่มที่ห่างกันชัด"""
    rng = np.random.default_rng(0)
    a = rng.normal(0, 1, 192); a /= np.linalg.norm(a)
    b = rng.normal(0, 1, 192); b /= np.linalg.norm(b)

    def near(v):
        e = v + rng.normal(0, 0.05, 192)
        return e / np.linalg.norm(e)

    h = SpeakerHandler()
    for _ in range(MIN_CLUSTER):        # คนแรกพูดจนสะสมพอ
        h.classify(near(a))
    assert h.stats()["speakers"] == 1, h.stats()
    first = h.classify(near(a))[0]
    assert first == 0, first

    for _ in range(MIN_CLUSTER):        # คนที่สองเข้ามา
        h.classify(near(b))
    assert h.stats()["speakers"] == 2, h.stats()

    assert h.classify(near(a))[0] == 0   # กลับมาคนแรก ต้องได้ id เดิม
    assert h.classify(near(b))[0] == 1
    print("diarize demo ok:", h.stats())


if __name__ == "__main__":
    demo()
