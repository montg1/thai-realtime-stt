# บันทึกการแก้ปัญหา

รวมปัญหาที่เจอระหว่างทำโปรเจกต์นี้และสาเหตุจริงของแต่ละอัน

---

## 1. โมเดลเริ่มต้นของอิมเมจใช้ไม่ได้

`montg1/realtimestt:v1.0-GPU` ตั้งค่ามาให้ใช้ `nectec-whisper-small-ct2` ซึ่ง
`faster_whisper/utils.py:29` แม็ปไปที่ `pattara12345/whisper-th-small-ct2`
repo นั้นตอบ **401 Repository Not Found** แล้ว (ถูกลบหรือเปลี่ยนเป็น private)

แก้โดยเปลี่ยนไปใช้ `nectec/Pathumma-whisper-th-large-v3` ซึ่งต้องแปลงเป็น CT2 ก่อน:

```bash
ct2-transformers-converter --model nectec/Pathumma-whisper-th-large-v3 \
  --output_dir models/Pathumma-whisper-th-large-v3-ct2-fp16 \
  --quantization float16 --copy_files preprocessor_config.json tokenizer_config.json \
  special_tokens_map.json added_tokens.json vocab.json merges.txt normalizer.json
```

repo ต้นทางไม่มี `tokenizer.json` ถ้าปล่อยไว้ faster-whisper จะ fallback ไปใช้
tokenizer ของ whisper-tiny (51865 tokens) ซึ่งไม่ตรงกับ large-v3 (51866) ต้องสร้างเพิ่ม:

```python
from transformers import WhisperTokenizerFast
t = WhisperTokenizerFast.from_pretrained("nectec/Pathumma-whisper-th-large-v3")
t.backend_tokenizer.save("models/Pathumma-whisper-th-large-v3-ct2-fp16/tokenizer.json")
```

---

## 2. ผลลัพธ์สุดท้ายแม่นน้อยกว่าข้อความสด

อาการแปลกที่โมเดล 1550M ให้ผลแย่กว่าโมเดล 244M สาเหตุอยู่ที่
`RealtimeSTT/audio_recorder.py:766-773` ซึ่งอิมเมจต้นทางแก้ไว้:

```python
segments = model.transcribe(
    audio,
    language="th",
    beam_size=1,                    # ฮาร์ดโค้ด — ค่าใน config ถูกเมิน
    #initial_prompt=initial_prompt, # คอมเมนต์ทิ้ง
    #suppress_tokens=suppress_tokens
)
```

`beam_size` ที่ตั้งไว้ใน `recorder_config` ไม่เคยถูกใช้เลย large-v3 จึงถอดรหัสแบบ
greedy ซึ่งมันหลอนและพูดวนซ้ำง่ายกว่าโมเดลเล็กมาก ส่วนสายเรียลไทม์
(`:1457`) ส่งพารามิเตอร์ครบตามปกติ จึงดูแม่นกว่าทั้งที่โมเดลเล็กกว่า

`patch/audio_recorder.py` แก้จุดนี้แล้ว — คืนค่า `beam_size` จาก config,
เปิด `initial_prompt` และ `suppress_tokens` กลับมา และเพิ่ม
`condition_on_previous_text=False` เพื่อกันลูปพูดซ้ำของ large-v3

---

## 3. VRAM ไม่พอสำหรับ large-v3 สองตัว

`recorder_config` โหลดโมเดลสองตัว (สายเรียลไทม์และสายสุดท้าย) ถ้าใช้ large-v3
ทั้งคู่จะกิน **8.59 GB บนการ์ด 8 GB เหลือว่าง 0.00 GB** โหลดขึ้นได้แต่ OOM ตอน inference

จับคู่แบบนี้แทน — เหลือ headroom ราว 3 GB:

| | โมเดล | VRAM รวม |
|---|---|---|
| สายเรียลไทม์ | whisper-th-small-ct2-int8 | 4982 MiB |
| สายสุดท้าย | Pathumma large-v3 fp16 | |

---

## ผลเปรียบเทียบโมเดลสายเรียลไทม์

ทดสอบด้วยประโยคเดียวกันจาก Windows TTS เสียงไทย (Microsoft Pattara):

> สวัสดีครับ ระบบถอดเสียงภาษาไทยแบบเรียลไทม์ กำลังทดสอบความแม่นยำของโมเดล

| โมเดล | ความถี่อัปเดต | ผลสุดท้ายถึงหน้าจอ | VRAM |
|---|---|---|---|
| distill-whisper-th-small | 18 ครั้ง | 7.20s | 5347 MiB |
| whisper-th-small-ct2-int8 | 11 ครั้ง | 8.58s | 4996 MiB |
| Thaweewat/whisper-th-medium-ct2 | 3 ครั้ง | 8.01s | 6405 MiB |

medium แม่นที่สุดระหว่างพูด distill เร็วที่สุดแต่แกว่งมากที่สุด
ผลสุดท้ายถูก 100% ทั้งสามแบบเพราะ Pathumma เป็นคนตัดสิน

---

## Typhoon ASR ไม่ใช่ streaming จริง

ชื่อรุ่นสื่อว่าเป็น realtime แต่ config บอกอีกอย่าง:

```
att_context_size : [-1, -1]     ← full context ทั้งซ้ายและขวา
att_context_style: regular      ← ไม่ใช่ chunked_limited
```

`[-1, -1]` คือโมเดลมองเสียงได้ทั้งประโยครวมถึงอนาคตตอนตัดสินแต่ละคำ ซึ่งเป็นโหมด
offline ถ้าจะสตรีมแบบ frame-by-frame จริงต้องเป็น cache-aware ที่เทรนด้วย context
จำกัด คำว่า realtime ในชื่อหมายถึงความเร็ว (RTFx) ไม่ใช่สถาปัตยกรรม

`typhoon_server.py` จึงถอดใหม่ทั้ง buffer ทุกรอบเหมือนที่ RealtimeSTT ทำ
ข้อความสดยังเปลี่ยนย้อนหลังได้ ต่างจาก RealtimeSTT ตรงที่ไม่มีโมเดลตัวที่สองมาตรวจซ้ำ

---

## ทำไม PCM ดิบ ไม่ใช่ .wav

WAV คือหัวไฟล์ 44 ไบต์ที่บอก sample rate และจำนวนช่อง บวกตัวเลข PCM ดิบ
หัวไฟล์มีไว้ให้คนเปิดไฟล์ทีหลังตีความถูก แต่ในสตรีมมิ่งทั้งสองฝั่งคุยกันสดอยู่แล้ว
metadata เลยย้ายไปอยู่ในทุก frame แทน

ที่สำคัญกว่านั้น WAV ต้องเขียนขนาดข้อมูลลงหัวไฟล์ตอนปิดไฟล์ ถ้าจะสตรีมด้วย WAV
แปลว่าต้องรอให้พูดจบก่อนถึงเขียนหัวไฟล์ได้ ซึ่งขัดกับคำว่าเรียลไทม์โดยตรง

Whisper และ NeMo รับ numpy array ไม่ได้รับไฟล์อยู่แล้ว การทำ .wav แล้วให้ถอดกลับ
จึงเป็นการเดินอ้อมเปล่า ๆ

---

## Docker image ขนาด 42.3 GB

`montg1/typhoon-asr:v1.0-GPU` สร้างด้วย `docker commit` ทับอิมเมจ RealtimeSTT
เดิม ผลคือมี CUDA สองชุดซ้อนกัน — CUDA 12.3 จาก base และ CUDA 13 ที่ pip ลากมา
ตอนอัป torch เป็น 2.14

`Dockerfile` ใน repo นี้สร้างใหม่จาก `python:3.10-slim` เพราะ torch wheel สมัยใหม่
มี CUDA runtime มาในตัวแล้ว ไม่ต้องมี OS-level CUDA อีกชั้น
