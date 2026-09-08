"""ดึงตัวอย่างภาษาไทยจาก speechcolab/gigaspeech2 (gated) มาทำชุดทดสอบ

  python3 fetch_gigaspeech2.py <out_dir> [n] [min_sec]

เขียน <out_dir>/NNN.pcm (16kHz mono int16) กับ <out_dir>/ref.json ให้ bench.py ใช้ต่อ
รูปแบบผลลัพธ์เหมือน fetch_ratchada.py ทุกอย่าง สลับชุดทดสอบได้โดยไม่ต้องแก้ bench.py

ทั้ง dataset 3.09 TB ภาษาไทยอย่างเดียว 1.28 TB แต่ที่ต้องโหลดจริงมีแค่
test.tsv 1.5 MB (เฉลย) ส่วนเสียงดึงทีละไฟล์ผ่าน datasets-server ไม่ต้องแตะ
test.tar.gz 1 GB เลย เพราะ webdataset ไม่มีข้อความ มีแต่ wav กับ __key__
"""
import json, os, subprocess, sys, urllib.parse, urllib.request

DS = "speechcolab/gigaspeech2"
CONFIG, SPLIT = "th", "test"
TSV = f"https://huggingface.co/datasets/{DS}/resolve/main/data/th/{SPLIT}.tsv"
API = "https://datasets-server.huggingface.co"
TOKEN = open(os.path.expanduser("~/.cache/huggingface/token")).read().strip()
HDRS = {"Authorization": f"Bearer {TOKEN}"}


def fetch(url, binary=False):
    with urllib.request.urlopen(urllib.request.Request(url, headers=HDRS)) as r:
        return r.read() if binary else json.load(r)


def rows(offset, length=100):
    q = urllib.parse.urlencode({"dataset": DS, "config": CONFIG, "split": SPLIT,
                                "offset": offset, "length": length})
    return fetch(f"{API}/rows?{q}")


def main(out_dir, n=50, min_sec=1.5):
    os.makedirs(out_dir, exist_ok=True)

    # เฉลยอยู่คนละไฟล์กับเสียง — webdataset มีแค่ wav ต้องจับคู่ด้วย key ท้ายสุดของ __key__
    text = dict(l.rstrip("\n").split("\t", 1)
                for l in fetch(TSV, binary=True).decode("utf-8").splitlines() if "\t" in l)

    total = rows(0, 1)["num_rows_total"]
    # กระจายทั้ง split — row ที่ติดกันมาจากคลิปต้นทางเดียวกัน (__key__ ขึ้นต้นเลขเดียวกัน)
    step = max(1, (total - 100) // 5)
    meta = []
    for i in range(6):
        meta += [r["row"] for r in rows(min(i * step, total - 100))["rows"]]

    print(f"ทั้ง split {total} rows -> ดึง metadata {len(meta)} -> คัดเอา {n}")

    ref, kept = {}, 0
    for r in meta:
        if kept >= n:
            break
        key = r["__key__"].split("/")[-1]
        label = text.get(key, "").strip()
        if not label:
            continue
        tag = f"{kept:03d}"
        raw = os.path.join(out_dir, f"{tag}.src")
        pcm = os.path.join(out_dir, f"{tag}.pcm")
        with open(raw, "wb") as f:
            f.write(fetch(r["wav"][0]["src"], binary=True))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", raw,
                        "-ac", "1", "-ar", "16000", "-f", "s16le", pcm], check=True)
        os.remove(raw)

        # ไม่มีคอลัมน์ความยาวใน metadata ต้องวัดจากไฟล์หลังแปลง (16k mono int16 = 32000 B/s)
        sec = os.path.getsize(pcm) / 32000
        if sec < min_sec:
            os.remove(pcm)
            continue
        ref[tag] = label
        kept += 1
        print(f"  {tag} {sec:5.2f}s  {label[:60]}", flush=True)

    json.dump(ref, open(os.path.join(out_dir, "ref.json"), "w"),
              ensure_ascii=False, indent=0)
    print(f"เขียน {len(ref)} ตัวอย่างที่ {out_dir}")


if __name__ == "__main__":
    main(sys.argv[1],
         int(sys.argv[2]) if len(sys.argv) > 2 else 50,
         float(sys.argv[3]) if len(sys.argv) > 3 else 1.5)
