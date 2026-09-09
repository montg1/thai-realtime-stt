# Thai Realtime STT

ถอดเสียงภาษาไทยแบบเรียลไทม์ผ่านเบราว์เซอร์ พร้อมแยกผู้พูด (speaker diarization)

| | |
|---|---|
| ASR | `nectec/Pathumma-stt-th-fastconformer-rnnt-large` (NeMo FastConformer-Transducer) |
| VAD | Silero VAD v6 |
| Diarization | pyannote WeSpeaker ResNet34-LM + online clustering |
| Backend | FastAPI + WebSocket |
| Frontend | React + Vite |
| Reverse proxy | Caddy (HTTPS) |

**VRAM ~1 GB · latency 0.76s · CER 25.99%** บนชุดทดสอบมาตรฐาน — ตัวเลขเต็มอยู่ใน
[`../results/README.md`](../results/README.md)

---

## ติดตั้ง

### สิ่งที่ต้องมี

- NVIDIA GPU มี VRAM 4 GB ขึ้นไป (ทดสอบบน RTX 3070 และ A30)
- Docker + [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
- พื้นที่ดิสก์ ~15 GB (อิมเมจ 11.7 GB + โมเดล 0.5 GB)

เช็คว่า GPU ใช้ใน Docker ได้:

```bash
docker run --rm --gpus all nvidia/cuda:12.3.1-base-ubuntu22.04 nvidia-smi
```

### 1. ตั้งค่า

```bash
cp .env.example .env
```

แก้ `SERVER_IP` ใน `.env` ให้เป็น IP ของเครื่องที่รัน — จำเป็นเพราะ Caddy ต้องออก
ใบรับรองให้ตรงกับ IP ที่เบราว์เซอร์เรียก

### 2. build

```bash
docker compose build
```

ครั้งแรกใช้เวลา ~10 นาที (torch + NeMo ก้อนใหญ่)

### 3. โหลดโมเดล

```bash
docker compose --profile bootstrap up bootstrap
```

ดาวน์โหลดไฟล์ `.nemo` 462 MB ลงโวลุ่ม `models` รันครั้งเดียวพอ

### 4. เปิดระบบ

```bash
docker compose up -d
```

รอ ~2 นาทีให้โหลดโมเดล ดูความคืบหน้าได้ที่:

```bash
docker compose logs -f api
```

พร้อมใช้เมื่อเห็น `ASR ready on :8000`

### 5. เปิดเบราว์เซอร์

```
https://<SERVER_IP>:9121/
```

ครั้งแรกจะเจอหน้าเตือนใบรับรอง กด **Advanced → Proceed**

---

## ต้องติดตั้ง root CA ถ้าจะใช้ไมโครโฟน

Chrome ให้ `getUserMedia` เฉพาะบน **secure context** — `https://` หรือ `http://localhost`
เท่านั้น LAN IP ธรรมดาไม่เข้าข่าย ไม่มีข้อยกเว้นให้ IP วงใน

ใบรับรองที่ Caddy ออกเองมีอายุ **12 ชั่วโมง** พอหมดอายุมันออกใบใหม่ แล้วข้อยกเว้นที่
เคยกดยอมรับใช้ไม่ได้ → WebSocket ถูกปฏิเสธเงียบ ๆ โดยไม่มีหน้าให้กดยอมรับ → ไมค์ตาย

แก้ครั้งเดียวจบด้วยการติดตั้ง root CA (อายุ 10 ปี) ที่เครื่อง client:

```bash
docker cp stt-caddy:/data/caddy/pki/authorities/local/root.crt .
```

Windows (PowerShell แบบ Administrator) แล้วปิด Chrome เปิดใหม่:

```powershell
Import-Certificate -FilePath .\root.crt -CertStoreLocation Cert:\LocalMachine\Root
```

Linux:

```bash
sudo cp root.crt /usr/local/share/ca-certificates/caddy-local.crt && sudo update-ca-certificates
```

---

## API

| endpoint | ใช้เมื่อ |
|---|---|
| `WS /v1/stream` | สตรีมเสียงสด รับผลกลับทันที |
| `POST /v1/transcribe` | อัปไฟล์ทั้งก้อน รอผลครั้งเดียว |
| `GET /v1/health` | ตรวจสถานะ + เวอร์ชัน |
| `GET /docs` | Swagger UI ลองยิงจากเบราว์เซอร์ได้ |

### ถอดไฟล์

```bash
curl -k -X POST -F "file=@meeting.mp3" https://<SERVER_IP>:9121/v1/transcribe
```

```json
{
  "version": "0.8.1",
  "duration_sec": 30.0,
  "text": "...",
  "segments": [
    {"text": "แล้วรถเนี่ยอีกคัน...", "audio_ms": 5120, "speaker": 0, "speaker_conf": 1.0},
    {"text": "โอนเข้าฮีต้า...", "audio_ms": 9472, "speaker": 1, "speaker_conf": 1.0}
  ]
}
```

### สตรีมสด

WebSocket สองทาง — ไม่ใช้ SSE เพราะ SSE เป็นทางเดียว server → client ไม่มีช่องส่งเสียงขึ้น

**ขาขึ้น** binary frame:

```
[4 ไบต์ int32 LE = ความยาว metadata][metadata JSON][PCM int16 LE mono]
```

`metadata` คือ `{"sampleRate": 48000}` — แนบไปทุกก้อนเพราะเป็นสตรีมสด ไม่มีจังหวะ
"เริ่มไฟล์" ให้ประกาศ และถ้าต่อใหม่กลางคันทุกก้อนก็อธิบายตัวเองได้

**ขาลง** text frame JSON:

```json
{"type":"hello","version":"0.8.1","model":"...","diarize":true}
{"type":"realtime","text":"กำลังพูด...","audio_ms":14208}
{"type":"fullSentence","text":"ประโยคสมบูรณ์","audio_ms":19200,"speaker":1,"speaker_conf":1.0}
```

`audio_ms` บอกว่าผลก้อนนี้ครอบคลุมเสียงถึงวินาทีไหนของสตรีม เอาไปลบกับปริมาณเสียง
ที่ส่งไปแล้วจะได้ความหน่วงจริง ไม่ขึ้นกับนาฬิกาเบราว์เซอร์หรือความหน่วงของเครือข่าย

---

## ระบบทำงานยังไง

```
Browser ──WSS──► Caddy ──ws──► FastAPI ──► Session ──► VAD ──┬──► ASR ──────► ข้อความ
 48kHz            :9121         :8000      resample          └──► Embedding ─► speaker
                                            16kHz
```

VAD เป็นด่านแรกเสมอ แล้วป้อนสองปลายทางด้วยข้อมูลคนละชุด:

| ปลายทาง | ได้อะไร | ทำไม |
|---|---|---|
| ASR | เสียงพูด **+ ความเงียบท้ายประโยค** | ต้องได้ยินพยัญชนะสะกด |
| Diarization | **เฉพาะเฟรมที่ VAD บอกว่าพูด** | ความเงียบทำให้ embedding เจือจางจนแยกคนแย่ลง |

ASR กับ diarization ทำงานขนานกัน ไม่ได้ต่อคิว — วัดแล้วเปิด diarization ไม่ทำให้ latency
ขยับเลย (0.75s เท่ากันทั้งเปิดและปิด)

**โมเดลไม่ได้รับสตรีม** — `model.transcribe()` รับ numpy array ทั้งก้อน ความรู้สึกเรียลไทม์
มาจากการเรียกซ้ำบนบัฟเฟอร์ที่โตขึ้นทุก 0.35 วินาที ถอดใหม่ทั้งก้อนทุกครั้ง นี่คือเหตุผล
ที่ข้อความสดเปลี่ยนย้อนหลังได้

---

## ปรับจูน

ทุกค่าอยู่ใน `.env` ปรับแล้ว `docker compose up -d api` ไม่ต้อง build ใหม่
ที่มาของแต่ละค่าอธิบายไว้ในคอมเมนต์ของ `typhoon_server.py` และ `diarize.py`

| ค่า | ค่าเริ่มต้น | ผลถ้าเปลี่ยน |
|---|---|---|
| `MAX_SEGMENT` | 5.0s | เพดานบังคับตัดประโยค วงสนทนาไม่มีช่วงเงียบให้ VAD ปิดประโยคเอง |
| `SEG_OVERLAP` | 0.6s | ยกท้ายประโยคไปเป็นต้นประโยคถัดไป กันคำขาดตรงรอยตัด |
| `DIAR_HOP` | 0.25s | ถี่ขึ้น = จับการเปลี่ยนคนละเอียดขึ้น แลกกับงาน GPU |
| `DIAR_WINDOW` | 3.0s | ยาวขึ้น = embedding นิ่งขึ้น แต่จับการสลับผู้พูดช้าลง |
| `DIARIZE` | 1 | ตั้ง 0 เพื่อปิด ประหยัด VRAM ~0.4 GB |

ดูค่าที่ใช้อยู่จริง:

```bash
docker compose logs api | grep CONFIG
```

---

## วัดผล

เครื่องมืออยู่ที่ระดับบนของ repo

```bash
python3 ../fetch_ratchada.py /tmp/rat 50      # ดึงชุดทดสอบ (ต้องมี HF token)
python3 ../bench.py stream /tmp/rat out.json ws://localhost:8000/v1/stream
python3 ../bench.py score /tmp/rat/ref.json out.json final
```

วัดความแม่นของ diarization ต้องใช้ `eval_diar.py` ไม่ใช่ `bench.py` — เพราะ `bench.py`
เปิด WebSocket ใหม่ทุกคลิป ทำให้ผู้พูดที่สะสมไว้รีเซ็ตทุกครั้ง

```bash
python3 ../eval_diar.py fetch /tmp/gt
python3 ../eval_diar.py run /tmp/gt ws://localhost:8000/v1/stream
```

---

## ข้อจำกัดที่รู้อยู่

**เสียงพูดทับกันแยกไม่ได้** — วิธี embedding + clustering ทำไม่ได้โดยธรรมชาติ
ถ้าต้องการต้องใช้ `pyannote/segmentation-3.0` ซึ่งเป็นคนละสถาปัตยกรรม

**คนสลับกันเร็วกว่า ~1 วินาทีจับไม่ทัน** — หน้าต่าง embedding ยาว 3 วินาที กว่าเสียง
คนใหม่จะครองหน้าต่างพอให้เห็นชัดก็ผ่านไปแล้ว

**ผู้พูดสะสมต่อการเชื่อมต่อ ไม่ใช่ต่อทั้งเซิร์ฟเวอร์** — เปิดสองแท็บคือคนละชุด
"คน 0" ของสองจอเป็นคนละคน (ตั้งใจ เพื่อไม่ให้คนละห้องประชุมปนกัน)

**ตัวเลขอารบิกไม่สม่ำเสมอ** — Pathumma เขียนเลขอารบิกได้ประมาณ 45% ของครั้งที่ควรได้
ถ้าต้องการ 100% ต้องทำ post-processing แปลงคำอ่านไทยเป็นตัวเลขเอง

---

## แก้ปัญหา

| อาการ | สาเหตุ |
|---|---|
| กดไมค์ไม่ได้ / ไม่มีเสียงเข้า | ไม่ได้เปิดผ่าน https หรือใบรับรองหมดอายุ — ติดตั้ง root CA |
| หน้าเว็บขึ้นแต่ไม่เชื่อมต่อ | `docker compose logs api` ดูว่าโหลดโมเดลเสร็จหรือยัง (~2 นาที) |
| แก้โค้ดแล้วไม่มีผล | `typhoon_server.py`/`diarize.py`/`api/` ถูก COPY เข้าอิมเมจ ต้อง `docker compose build api` |
| ไม่แน่ใจว่ารันโค้ดล่าสุด | `docker compose logs api \| grep -E "VERSION\|CONFIG"` |

---

## โครงสร้าง

```
api/main.py         FastAPI — WebSocket + REST
typhoon_server.py   engine: VAD, ตัดประโยค, จัดคิวถอดเสียง
diarize.py          แยกผู้พูด (ตรรกะจาก github.com/maximus-choi/Utterr)
web/                React + Vite
Dockerfile          อิมเมจ API (GPU)
docker-compose.yml  api + web + caddy
Caddyfile           HTTPS + เราต์
version.json        เวอร์ชันและบันทึกว่าแต่ละรุ่นแก้อะไร
NOTES.md            บันทึกปัญหาที่เจอระหว่างทางและสาเหตุจริง
```

`models/` ไม่ได้อยู่ใน repo — โหลดด้วย profile `bootstrap`
