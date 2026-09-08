"""วัดความแม่นของ diarization ด้วยชุดที่มี speaker label จริง

  python3 eval_diar.py fetch <out_dir>          # ดึง Thanarit/Thai-Voice-Test-Speaker-Only
  python3 eval_diar.py run <dir> <ws_url>       # ยิงเข้าเซิร์ฟเวอร์แล้ววัด

ต่อคลิปเรียงกันในการเชื่อมต่อเดียว คั่นด้วยความเงียบ 1.2s ให้ VAD ตัดทีละคลิป
สถานะผู้พูดจึงสะสมข้ามคลิปเหมือนใช้งานจริง ไม่ใช่รีเซ็ตทุกครั้ง

วัดด้วย pairwise agreement เพราะ speaker id ที่ระบบตั้งเป็นเลขอะไรก็ได้ เทียบตรง ๆ
กับ label ไม่ได้ จึงถามแทนว่า "ทุกคู่ของคลิป ระบบตอบเหมือน/ต่างตรงกับความจริงมั้ย"
ซึ่งไม่ขึ้นกับว่า id ถูกตั้งชื่อว่าอะไร
"""
import asyncio, json, os, subprocess, sys, urllib.parse, urllib.request

DS = "Thanarit/Thai-Voice-Test-Speaker-Only"
API = "https://datasets-server.huggingface.co"
SR, CHUNK = 16000, 512
HDR = json.dumps({"sampleRate": SR}).encode()
PREFIX = len(HDR).to_bytes(4, "little") + HDR
SIL = PREFIX + b"\x00" * (CHUNK * 2)
GAP_FRAMES = 38          # ~1.2s ความเงียบคั่น ต้องมากกว่า SILENCE_TO_FINALIZE (0.7s)


def _hdrs():
    tok = open(os.path.expanduser("~/.cache/huggingface/token")).read().strip()
    return {"Authorization": f"Bearer {tok}"}


def fetch(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    q = urllib.parse.urlencode({"dataset": DS, "config": "default",
                                "split": "train", "offset": 0, "length": 100})
    req = urllib.request.Request(f"{API}/rows?{q}", headers=_hdrs())
    rows = [r["row"] for r in json.load(urllib.request.urlopen(req))["rows"]]

    truth = {}
    for i, r in enumerate(rows):
        tag = f"{i:03d}"
        raw, pcm = f"{out_dir}/{tag}.src", f"{out_dir}/{tag}.pcm"
        with open(raw, "wb") as f:
            f.write(urllib.request.urlopen(
                urllib.request.Request(r["audio"][0]["src"], headers=_hdrs())).read())
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", raw,
                        "-ac", "1", "-ar", "16000", "-f", "s16le", pcm], check=True)
        os.remove(raw)
        truth[tag] = r["speaker_id"]
        print(f"  {tag} {r['speaker_id']} {r['length']:.1f}s")
    json.dump(truth, open(f"{out_dir}/truth.json", "w"), indent=0)
    print(f"เขียน {len(truth)} คลิปที่ {out_dir}")


async def _run(pcm_dir, uri):
    import websockets
    truth = json.load(open(f"{pcm_dir}/truth.json"))
    tags = sorted(truth)
    got = []                       # [(ลำดับคลิปที่กำลังเล่น, speaker ที่ทาย)]
    playing = [0]

    async with websockets.connect(uri, max_size=None) as ws:
        async def reader():
            async for m in ws:
                d = json.loads(m)
                if d["type"] == "fullSentence":
                    got.append((playing[0], d.get("speaker")))

        t = asyncio.ensure_future(reader())
        for i, tag in enumerate(tags):
            playing[0] = i
            pcm = open(f"{pcm_dir}/{tag}.pcm", "rb").read()
            for j in range(0, len(pcm), CHUNK * 2):
                await ws.send(PREFIX + pcm[j:j + CHUNK * 2])
                await asyncio.sleep(0.032)
            for _ in range(GAP_FRAMES):
                await ws.send(SIL)
                await asyncio.sleep(0.032)
        await asyncio.sleep(4)
        t.cancel()

    # คลิปหนึ่งอาจถูกตัดเป็นหลายประโยค เอาคำตอบแรกที่ไม่ใช่ None ของคลิปนั้น
    pred = {}
    for idx, spk in got:
        if tags[idx] not in pred and spk is not None:
            pred[tags[idx]] = spk
    return truth, pred, len(got)


def score(truth, pred):
    tags = [t for t in sorted(truth) if t in pred]
    same_t = same_p = agree = 0
    tp = fp = fn = 0
    for i in range(len(tags)):
        for j in range(i + 1, len(tags)):
            a, b = tags[i], tags[j]
            t_same = truth[a] == truth[b]
            p_same = pred[a] == pred[b]
            agree += t_same == p_same
            same_t += t_same
            same_p += p_same
            tp += t_same and p_same
            fp += (not t_same) and p_same
            fn += t_same and (not p_same)
    n = len(tags) * (len(tags) - 1) // 2
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {"n_clips": len(tags), "n_pairs": n,
            "pairwise_acc": agree / n if n else 0.0,
            "precision": prec, "recall": rec, "f1": f1,
            "true_speakers": len(set(truth[t] for t in tags)),
            "pred_speakers": len(set(pred[t] for t in tags))}


if __name__ == "__main__":
    if sys.argv[1] == "fetch":
        fetch(sys.argv[2])
    else:
        truth, pred, n_msg = asyncio.get_event_loop().run_until_complete(
            _run(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "ws://localhost:9005"))
        s = score(truth, pred)
        print(f"ได้ประโยคทั้งหมด {n_msg} | ตอบได้ {s['n_clips']}/{len(truth)} คลิป")
        print(f"คนจริง {s['true_speakers']}  ระบบทาย {s['pred_speakers']}")
        print(f"pairwise accuracy {s['pairwise_acc']*100:.1f}%  "
              f"P {s['precision']*100:.1f}%  R {s['recall']*100:.1f}%  F1 {s['f1']*100:.1f}%")
        for t in sorted(pred):
            print(f"  {t} จริง={truth[t]} ทาย={pred[t]}")
