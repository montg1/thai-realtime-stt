import asyncio, websockets, json, struct, wave, sys, time
import numpy as np

WAV = "/work/test_th.wav"

async def main():
    w = wave.open(WAV, 'rb')
    sr, n, ch = w.getframerate(), w.getnframes(), w.getnchannels()
    pcm = w.readframes(n)
    dur = n / sr
    print(f"[audio] {dur:.2f}s  {sr}Hz  ch={ch}  {len(pcm)} bytes", flush=True)
    if ch == 2:
        a = np.frombuffer(pcm, dtype=np.int16).reshape(-1, 2).mean(axis=1).astype(np.int16)
        pcm = a.tobytes()

    async with websockets.connect('ws://localhost:9001', max_size=None) as ws:
        meta = json.dumps({'sampleRate': sr}).encode()
        hdr = struct.pack('<I', len(meta)) + meta
        chunk = int(sr * 0.1) * 2                      # 100ms frames, like the browser
        t_start = time.time()

        async def feed():
            for i in range(0, len(pcm), chunk):
                await ws.send(hdr + pcm[i:i+chunk])
                await asyncio.sleep(0.1)               # stream in real time
            print(f"[audio] finished streaming at {time.time()-t_start:.2f}s", flush=True)

        async def recv():
            while True:
                r = json.loads(await ws.recv())
                el = time.time() - t_start
                if r['type'] == 'realtime':
                    print(f"  [{el:6.2f}s] สด    : {r['text']}", flush=True)
                else:
                    print(f"  [{el:6.2f}s] สุดท้าย: {r['text']}", flush=True)

        task = asyncio.ensure_future(recv())
        await feed()
        try:
            await asyncio.wait_for(task, timeout=30)
        except asyncio.TimeoutError:
            print("[done] หมดเวลารอ 30s หลังเสียงจบ", flush=True)

asyncio.run(main())
