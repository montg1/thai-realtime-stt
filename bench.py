"""Benchmark RealtimeSTT ผ่าน websocket จริง — วัด CER + latency

  python3 bench.py stream <pcm_dir> <out.json>   # ยิงเสียงเข้า ws://localhost:9001
  python3 bench.py score <ref.json> <out.json>   # เทียบผลกับเฉลย
  python3 bench.py selftest

pcm = 16kHz mono int16 ดิบ, ชื่อไฟล์ <key>.pcm ให้ตรงกับ key ใน ref.json
"""
import asyncio, glob, json, os, re, sys, time, unicodedata

SR, CHUNK = 16000, 512
HDR = json.dumps({"sampleRate": SR}).encode()
PREFIX = len(HDR).to_bytes(4, "little") + HDR
SIL = PREFIX + b"\x00" * (CHUNK * 2)
QUIET = 4.0        # เงียบจากฝั่ง server เท่านี้ ถือว่าถอดครบแล้ว
MAX_WAIT = 40.0    # กันค้างถ้า server ไม่ตอบอะไรเลย


async def _one(path, uri):
    """คืนผลทั้งสายสตรีม (realtime) และสายสรุป (fullSentence) ในรอบเดียว

    เวลาอ้างอิง 2 จุด: audio_start = เริ่มส่งเสียงพูดจริง (หลังความเงียบนำ),
    audio_end = ส่งเสียงก้อนสุดท้ายจบ ค่า rt_last ติดลบได้ ถ้าโมเดลตามทัน
    ตั้งแต่ก่อนเสียงหมด

    คลิปยาว (เช่น TVSpeech ~29s) จะถูก VAD ตัดเป็นหลายประโยค จึงเก็บ fullSentence
    ให้ครบทุกอันแล้วต่อกัน ไม่ใช่หยุดที่อันแรก และรอจนฝั่ง server เงียบ QUIET วินาที
    แทนการรอข้อความอันแรกแล้วจบ
    """
    import websockets
    pcm = open(path, "rb").read()
    async with websockets.connect(uri) as ws:
        rt = []          # [(เวลา, ข้อความ)] realtime ทุกครั้ง ตลอดทั้งคลิป
        fin = []         # [(เวลา, ข้อความ)] fullSentence ทุกประโยค
        parts = []       # realtime ตัวท้ายของแต่ละประโยค = สิ่งที่ผู้ใช้เห็นบนจอจริง
        cur = [""]       # realtime ล่าสุดของประโยคที่กำลังพูด
        quiet_from = [time.time()]

        async def reader():
            async for m in ws:
                d = json.loads(m)
                quiet_from[0] = time.time()
                if d["type"] == "realtime":
                    if d["text"].strip():
                        rt.append((time.time(), d["text"]))
                        cur[0] = d["text"]
                elif d["type"] == "fullSentence":
                    fin.append((time.time(), d["text"]))
                    parts.append(cur[0])
                    cur[0] = ""

        async def tail():   # VAD ต้องเห็นความเงียบถึงจะตัดจบประโยค
            for _ in range(90):
                await ws.send(SIL)
                await asyncio.sleep(0.032)

        t = asyncio.ensure_future(reader())
        for _ in range(16):
            await ws.send(SIL)
            await asyncio.sleep(0.032)
        audio_start = time.time()
        for i in range(0, len(pcm), CHUNK * 2):
            await ws.send(PREFIX + pcm[i:i + CHUNK * 2])
            await asyncio.sleep(0.032)   # เดินตามเวลาจริง ไม่งั้น VAD เพี้ยน
        audio_end = time.time()
        ta = asyncio.ensure_future(tail())

        deadline = time.time() + MAX_WAIT
        while time.time() < deadline:
            await asyncio.sleep(0.2)
            if fin and time.time() - quiet_from[0] > QUIET:
                break
        ta.cancel()
        t.cancel()
        if cur[0]:
            parts.append(cur[0])   # realtime ที่ค้างโดยไม่มี fullSentence ตามมา

        return {
            "text": " ".join(x for _, x in fin),
            "latency": round(fin[-1][0] - audio_end, 2) if fin else None,
            "n_sentences": len(fin),
            "rt_text": " ".join(x for x in parts if x),
            "rt_first": round(rt[0][0] - audio_start, 2) if rt else None,
            "rt_last": round(rt[-1][0] - audio_end, 2) if rt else None,
            "rt_n": len(rt),
        }


async def _stream(pcm_dir, out_path, uri):
    out = {}
    for p in sorted(glob.glob(os.path.join(pcm_dir, "*.pcm"))):
        k = os.path.splitext(os.path.basename(p))[0]
        out[k] = r = await _one(p, uri)
        print(f"{k} rt_first {r['rt_first']} rt_last {r['rt_last']} "
              f"n {r['rt_n']} | {r['rt_text']}", flush=True)
    json.dump(out, open(out_path, "w"), ensure_ascii=False, indent=0)


def norm(s):
    # ต้อง NFKC ไม่ใช่ NFC — ไทยอยู่ใน composition exclusion ทำให้ NFC ไม่รวม
    # "ํา" (U+0E4D+U+0E32) กับ "ำ" (U+0E33) ที่หน้าตาเหมือนกันเป๊ะเข้าด้วยกัน
    s = unicodedata.normalize("NFKC", s)
    for c in ".?!":
        s = s.replace(c, "")
    return re.sub(r"\s+", "", s)               # ไทยไม่มีขอบเขตคำ ช่องว่างไม่ควรถูกนับผิด


def lev(x, y):
    if len(x) < len(y):
        x, y = y, x
    prev = list(range(len(y) + 1))
    for i, cx in enumerate(x, 1):
        cur = [i]
        for j, cy in enumerate(y, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (cx != cy)))
        prev = cur
    return prev[-1]


def _avg(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else 0.0


def score(ref, out, mode="final"):
    """mode='final' วัดสาย fullSentence, mode='realtime' วัดสายสตรีม"""
    field = "text" if mode == "final" else "rt_text"
    errs, total, per = 0, 0, {}
    for k, r in ref.items():
        R, H = norm(r), norm(out.get(k, {}).get(field, ""))
        per[k] = lev(R, H)
        errs += per[k]
        total += len(R)
    vals = list(out.values())
    return {
        "cer": errs / total if total else 0.0,
        "exact": sum(1 for d in per.values() if d == 0),
        "n": len(ref),
        "latency": _avg(v.get("latency") for v in vals),
        "rt_first": _avg(v.get("rt_first") for v in vals),
        "rt_last": _avg(v.get("rt_last") for v in vals),
        "rt_n": _avg(v.get("rt_n") for v in vals),
        "empty": sum(1 for k in ref if not out.get(k, {}).get(field, "").strip()),
        "per_item": per,
    }


def selftest():
    assert lev("abc", "abc") == 0
    assert lev("abc", "abd") == 1
    assert lev("", "abc") == 3
    assert norm("ลอง ชิม สลัด.") == "ลองชิมสลัด"
    assert norm("สําหรับ") == norm("สำหรับ")   # U+0E4D+0E32 ต้องเท่ากับ U+0E33
    assert lev(norm("สําหรับ"), norm("สำหรับ")) == 0
    # คลิปยาวถูกตัดเป็นหลายประโยค ต่อกันด้วยช่องว่างซึ่ง norm() ตัดทิ้งอยู่แล้ว
    assert norm("สวัสดี ครับ") == norm("สวัสดีครับ")
    ref = {"a": "สวัสดี", "b": "ขอบคุณ"}
    out = {"a": {"text": "สวัสดี.", "rt_text": "สวัสดี", "latency": 0.5,
                 "rt_first": 0.4, "rt_last": -0.1, "rt_n": 3},
           "b": {"text": "ขอบคุน", "rt_text": "ขอบ", "latency": 1.5,
                 "rt_first": 0.6, "rt_last": 0.1, "rt_n": 1}}
    s = score(ref, out)
    assert s["exact"] == 1, s
    assert abs(s["cer"] - 1 / 12) < 1e-9, s   # ผิด 1 ตัว จากทั้งหมด 12 ตัว
    assert abs(s["latency"] - 1.0) < 1e-9, s
    r = score(ref, out, "realtime")
    assert r["exact"] == 1, r                 # 'สวัสดี' ตรง, 'ขอบ' ขาด 3 ตัว
    assert abs(r["cer"] - 3 / 12) < 1e-9, r
    assert abs(r["rt_first"] - 0.5) < 1e-9, r
    assert abs(r["rt_last"] - 0.0) < 1e-9, r
    assert r["empty"] == 0, r
    print("selftest ok")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "selftest"
    if cmd == "stream":
        uri = sys.argv[4] if len(sys.argv) > 4 else "ws://localhost:9001"
        asyncio.get_event_loop().run_until_complete(_stream(sys.argv[2], sys.argv[3], uri))
    elif cmd == "score":
        ref = json.load(open(sys.argv[2]))
        out = json.load(open(sys.argv[3]))
        mode = sys.argv[4] if len(sys.argv) > 4 else "final"
        field = "text" if mode == "final" else "rt_text"
        s = score(ref, out, mode)
        print(f"[{mode}] CER {s['cer']*100:.2f}%   ถูกเป๊ะ {s['exact']}/{s['n']}   "
              f"ว่าง {s['empty']}")
        if mode == "final":
            print(f"  latency (จบเสียง -> fullSentence) {s['latency']:.2f}s")
        else:
            print(f"  rt_first (เริ่มพูด -> ตัวอักษรแรก) {s['rt_first']:.2f}s")
            print(f"  rt_last  (จบเสียง -> อัปเดตท้ายสุด) {s['rt_last']:.2f}s")
            print(f"  อัปเดตเฉลี่ย {s['rt_n']:.1f} ครั้ง/ประโยค")
        for k, d in sorted(s["per_item"].items(), key=lambda x: -x[1])[:10]:
            if d:
                print(f"  [{k}] err {d}\n    ref: {ref[k]}\n    hyp: {out[k].get(field,'')}")
    else:
        selftest()
