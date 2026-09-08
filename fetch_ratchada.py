"""ดึงตัวอย่างจาก ThinkingMachinesDataScience/Ratchada-STT (gated) มาทำชุดทดสอบ

  python3 fetch_ratchada.py <out_dir> [n] [min_sec]

เขียน <out_dir>/NNN.pcm (16kHz mono int16) กับ <out_dir>/ref.json ให้ bench.py ใช้ต่อ
สุ่มกระจายทั้ง split เพราะ row ที่ติดกันมาจากคลิปต้นทางเดียวกัน ถ้าเอาแต่ต้นจะได้ผู้พูดคนเดียว
"""
import json, os, subprocess, sys, urllib.parse, urllib.request

DS = "ThinkingMachinesDataScience/Ratchada-STT"
SPLIT = "test"
TOKEN = open(os.path.expanduser("~/.cache/huggingface/token")).read().strip()
API = "https://datasets-server.huggingface.co"


def get(url):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
    return json.load(urllib.request.urlopen(req))


def total_rows():
    q = urllib.parse.urlencode({"dataset": DS, "config": "default", "split": SPLIT,
                                "offset": 0, "length": 1})
    return get(f"{API}/rows?{q}")["num_rows_total"]


def windows(n_win, total, per=100):
    step = max(1, (total - per) // max(1, n_win - 1))
    return [min(i * step, total - per) for i in range(n_win)]


def main(out_dir, n=50, min_sec=1.5):
    os.makedirs(out_dir, exist_ok=True)
    total = total_rows()
    rows = []
    for off in windows(6, total):
        q = urllib.parse.urlencode({"dataset": DS, "config": "default", "split": SPLIT,
                                    "offset": off, "length": 100})
        rows += [r["row"] for r in get(f"{API}/rows?{q}")["rows"]]

    keep = [r for r in rows if r["end"] - r["start"] >= min_sec and r["label"].strip()]
    step = max(1, len(keep) // n)
    keep = keep[::step][:n]
    print(f"ทั้ง split {total} rows -> ดึงมาดู {len(rows)} -> ใช้ {len(keep)} "
          f"(ยาว >= {min_sec}s)")

    ref = {}
    for i, r in enumerate(keep):
        k = f"{i:03d}"
        src = r["audio"][0]["src"]
        raw = os.path.join(out_dir, f"{k}.src")
        req = urllib.request.Request(src, headers={"Authorization": f"Bearer {TOKEN}"})
        with open(raw, "wb") as f:
            f.write(urllib.request.urlopen(req).read())
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", raw,
                        "-ac", "1", "-ar", "16000", "-f", "s16le",
                        os.path.join(out_dir, f"{k}.pcm")], check=True)
        os.remove(raw)
        ref[k] = r["label"]
        print(f"  {k} {r['end']-r['start']:5.2f}s  {r['label'][:60]}", flush=True)

    json.dump(ref, open(os.path.join(out_dir, "ref.json"), "w"),
              ensure_ascii=False, indent=0)
    print(f"เขียน {len(ref)} ตัวอย่างที่ {out_dir}")


if __name__ == "__main__":
    main(sys.argv[1],
         int(sys.argv[2]) if len(sys.argv) > 2 else 50,
         float(sys.argv[3]) if len(sys.argv) > 3 else 1.5)
