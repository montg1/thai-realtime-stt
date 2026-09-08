"""ดึงตัวอย่างจาก typhoon-ai/TVSpeech มาทำชุดทดสอบ

  python3 fetch_tvspeech.py <out_dir> [n]

เขียน <out_dir>/NNN.pcm (16kHz mono int16) กับ <out_dir>/ref.json ให้ bench.py ใช้ต่อ

ชุดนี้เป็น long-form — คลิปละ ~29 วินาที ข้อความ ~300 ตัวอักษร ต่างจาก Ratchada
(p50 1.58s) และ GigaSpeech2 (p50 4.70s) มาก VAD จะตัดคลิปเดียวเป็นหลายประโยค
ต้องใช้ bench.py ที่เก็บ fullSentence ครบทุกอันแล้วต่อกัน ไม่ใช่เอาแค่อันแรก

เวลาที่ใช้ต่อคลิปคือ ~29s (สตรีมตามเวลาจริง) + tail + QUIET จึงตั้ง n ไว้น้อยกว่าชุดอื่น
"""
import json, os, subprocess, sys, urllib.parse, urllib.request

DS = "typhoon-ai/TVSpeech"
SPLIT = "test"
API = "https://datasets-server.huggingface.co"
TOKEN = open(os.path.expanduser("~/.cache/huggingface/token")).read().strip()
HDRS = {"Authorization": f"Bearer {TOKEN}"}


def fetch(url, binary=False):
    with urllib.request.urlopen(urllib.request.Request(url, headers=HDRS)) as r:
        return r.read() if binary else json.load(r)


def rows(offset, length=100):
    q = urllib.parse.urlencode({"dataset": DS, "config": "default", "split": SPLIT,
                                "offset": offset, "length": length})
    return fetch(f"{API}/rows?{q}")


def main(out_dir, n=30):
    os.makedirs(out_dir, exist_ok=True)
    total = rows(0, 1)["num_rows_total"]

    # row ที่ติดกันมาจากคลิป YouTube เดียวกัน (audio_id ขึ้นต้นด้วย video id เดียวกัน)
    # ถ้าเอาแต่ต้น split จะได้ผู้พูดคนเดียว ต้องกระจาย
    step = max(1, (total - 100) // 5)
    meta = []
    for i in range(6):
        meta += [r["row"] for r in rows(min(i * step, max(0, total - 100)))["rows"]]

    step2 = max(1, len(meta) // n)
    meta = meta[::step2][:n]
    print(f"ทั้ง split {total} rows -> ใช้ {len(meta)}")

    ref = {}
    for i, r in enumerate(meta):
        tag = f"{i:03d}"
        raw = os.path.join(out_dir, f"{tag}.src")
        pcm = os.path.join(out_dir, f"{tag}.pcm")
        with open(raw, "wb") as f:
            f.write(fetch(r["audio"][0]["src"], binary=True))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", raw,
                        "-ac", "1", "-ar", "16000", "-f", "s16le", pcm], check=True)
        os.remove(raw)
        ref[tag] = r["sentence"]
        print(f"  {tag} {os.path.getsize(pcm)/32000:6.2f}s  {r['sentence'][:55]}", flush=True)

    json.dump(ref, open(os.path.join(out_dir, "ref.json"), "w"),
              ensure_ascii=False, indent=0)
    print(f"เขียน {len(ref)} ตัวอย่างที่ {out_dir}")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 30)
