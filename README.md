# Thai Realtime Speech-to-Text

เปรียบเทียบสองสถาปัตยกรรมสำหรับการถอดเสียงภาษาไทยแบบเรียลไทม์ผ่านเบราว์เซอร์

| | RealtimeSTT | Typhoon ASR |
|---|---|---|
| สถาปัตยกรรม | Whisper (encoder-decoder) | FastConformer-Transducer (RNNT) |
| เอนจิน | faster-whisper / CTranslate2 | NVIDIA NeMo |
| โมเดล | Pathumma large-v3 + small (สองตัว) | typhoon-asr-realtime 114M (ตัวเดียว) |
| หน้าเว็บ | `:8000` | `:8001` |
| WebSocket | `:9001` | `:9002` |

ทั้งสองระบบใช้โปรโตคอลเดียวกัน เสียงจากไมค์ถูกส่งเป็น PCM ดิบ ไม่ผ่านไฟล์:

```
[4 ไบต์ little-endian: ความยาว metadata][metadata JSON][int16 PCM]
```

---

## เริ่มใช้งาน

### Typhoon ASR

```bash
docker build -t typhoon-asr:v2-slim .
docker run -d --name typhoon-ws --gpus all -p 9002:9002 \
  -v typhoon-models:/models -v "$PWD/typhoon_server.py:/app/typhoon_server.py:ro" \
  typhoon-asr:v2-slim
docker run -d --name typhoon-web -p 8001:8001 \
  -v "$PWD/typhoon_client:/srv:ro" -w /srv \
  python:3.10-slim python3 -m http.server 8001 --bind 0.0.0.0
```

เปิด <http://localhost:8001> โมเดลดาวน์โหลดครั้งแรกอัตโนมัติลง volume `typhoon-models`

### RealtimeSTT

```bash
./start.sh          # เปิดทั้ง STT server และหน้าเว็บ
docker rm -f rtstt  # ปิด
```

เปิด <http://localhost:8000> รายละเอียดการตั้งค่าอยู่ใน [`NOTES.md`](NOTES.md)

> ต้องเปิดผ่าน `http://localhost` เท่านั้น Chrome บล็อกไมโครโฟนบน `file://`

---

## โครงสร้าง

```
Dockerfile              อิมเมจ Typhoon ASR (slim, ~10 GB)
typhoon_server.py       WebSocket server + VAD segmentation
typhoon_client/         หน้าเว็บ Typhoon (ปุ่มไมค์ มิเตอร์เสียง สถานะ)
example_browserclient/  หน้าเว็บและ server ของ RealtimeSTT
patch/audio_recorder.py RealtimeSTT ที่แก้บั๊ก beam_size แล้ว
start.sh                สคริปต์เปิด RealtimeSTT
NOTES.md                บันทึกปัญหาที่เจอและวิธีแก้
```

`models/` ไม่ได้อยู่ใน repo — น้ำหนักโมเดลรวมหลาย GB ดาวน์โหลดหรือแปลงเอาเองตาม `NOTES.md`

---

## ความต้องการของระบบ

NVIDIA GPU ที่มี VRAM 8 GB ขึ้นไป (พัฒนาและทดสอบบน RTX 3070, driver 591.86),
Docker พร้อม GPU support, และเบราว์เซอร์ที่รองรับ `getUserMedia`

RealtimeSTT ใช้ VRAM ราว 5 GB เมื่อโหลดสองโมเดลพร้อมกัน ส่วน Typhoon ใช้ราว 1.5 GB
