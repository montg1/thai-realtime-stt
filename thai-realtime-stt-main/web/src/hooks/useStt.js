/* hook เดียวที่ทั้งหน้าไมค์และหน้าวัดผลใช้ร่วมกัน
 *
 * ของเดิมมี client.js กับ prove.js ที่ทำเรื่องเดียวกันคนละชุด แก้ทีต้องแก้สองที่
 * รวมมาไว้ที่นี่แล้วให้แต่ละหน้าเลือกแสดงเฉพาะสิ่งที่ตัวเองสนใจ
 *
 * หน่วงวัดจาก "เวลาในสตรีมเสียง": เซิร์ฟเวอร์บอก audio_ms ว่าผลก้อนนี้ครอบคลุมเสียง
 * ถึงวินาทีไหน ลบกับปริมาณเสียงที่ส่งไปแล้วได้หน่วงจริง ไม่ขึ้นกับนาฬิกาเบราว์เซอร์
 * หรือความหน่วงของเครือข่าย
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { CHUNK, encodeChunk, wsUrl } from "../lib/protocol";

export function useStt() {
  const [connected, setConnected] = useState(false);
  const [info, setInfo] = useState(null);        // hello: version/model/diarize
  const [sentences, setSentences] = useState([]);
  const [interim, setInterim] = useState("");
  const [mode, setMode] = useState(null);        // null | "mic" | "file"
  const [bands, setBands] = useState(() => new Array(13).fill(0));  // มิเตอร์ 13 ย่าน
  const [play, setPlay] = useState({ pos: 0, dur: 0 });
  const [stats, setStats] = useState({ lags: [], rtFirst: null, points: [], drift: 0, sent: 0 });

  const ws = useRef(null);
  const sentSamples = useRef(0);
  const rate = useRef(48000);
  const audio = useRef({});                      // ctx/node/src/stream/player
  const raf = useRef(0);

  /* ---------- websocket ---------- */
  useEffect(() => {
    let closed = false, timer;
    const open = () => {
      const s = new WebSocket(wsUrl());
      ws.current = s;
      s.onopen = () => setConnected(true);
      s.onclose = () => {
        setConnected(false);
        if (!closed) timer = setTimeout(open, 3000);   // ต่อใหม่เองเมื่อหลุด
      };
      s.onmessage = ev => {
        const d = JSON.parse(ev.data);
        if (d.type === "hello") { setInfo(d); return; }

        const sentMs = sentSamples.current / rate.current * 1000;
        const lag = d.audio_ms == null ? null : (sentMs - d.audio_ms) / 1000;

        if (d.type === "realtime") {
          setInterim(d.text);
          if (lag != null) setStats(p => ({
            ...p,
            rtFirst: p.rtFirst ?? lag,
            points: [...p.points, { x: d.audio_ms / 1000, y: lag, kind: "rt" }],
          }));
        } else if (d.type === "fullSentence") {
          setInterim("");
          setSentences(p => [...p, { ...d, lag }]);
          if (lag != null) setStats(p => ({
            ...p,
            lags: [...p.lags, lag],
            points: [...p.points, { x: d.audio_ms / 1000, y: lag, kind: "final" }],
          }));
        }
      };
    };
    open();
    return () => { closed = true; clearTimeout(timer); ws.current?.close(); };
  }, []);

  /* ---------- ส่งเสียง ---------- */
  const send = useCallback((f32, elapsed) => {
    const s = ws.current;
    if (!s || s.readyState !== WebSocket.OPEN) return;
    s.send(encodeChunk(f32, rate.current));
    sentSamples.current += f32.length;
    const sent = sentSamples.current / rate.current;
    // ดริฟต์ต้องใกล้ 0 ไม่งั้นแปลว่าส่งเร็ว/ช้ากว่าเวลาจริง แล้วตัวเลขหน่วงเชื่อไม่ได้
    setStats(p => ({ ...p, sent, drift: elapsed - sent }));
  }, []);

  const reset = () => {
    sentSamples.current = 0;
    setSentences([]); setInterim("");
    setStats({ lags: [], rtFirst: null, points: [], drift: 0, sent: 0 });
    setPlay({ pos: 0, dur: 0 });
  };

  const stop = useCallback(() => {
    cancelAnimationFrame(raf.current);
    const a = audio.current;
    try { a.player?.stop(); } catch {}
    a.node?.disconnect(); a.src?.disconnect();
    a.stream?.getTracks().forEach(t => t.stop());
    a.ctx?.close();
    audio.current = {};
    setMode(null); setBands(new Array(13).fill(0));
  }, []);

  const startMic = useCallback(async () => {
    reset();
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const ctx = new AudioContext();
    rate.current = ctx.sampleRate;
    const src = ctx.createMediaStreamSource(stream);
    const analyser = ctx.createAnalyser(); analyser.fftSize = 128;
    const node = ctx.createScriptProcessor(CHUNK, 1, 1);
    const t0 = performance.now();
    node.onaudioprocess = e => send(e.inputBuffer.getChannelData(0),
                                    (performance.now() - t0) / 1000);
    src.connect(analyser); src.connect(node); node.connect(ctx.destination);
    audio.current = { ctx, src, node, stream, analyser };
    setMode("mic");

    // เฉลี่ยเป็นย่านความถี่เหมือนของเดิม แท่งจะได้ขยับไม่พร้อมกันเป็นสเปกตรัมจริง
    const tick = () => {
      const buf = new Uint8Array(analyser.frequencyBinCount);
      analyser.getByteFrequencyData(buf);
      const step = Math.floor(buf.length / 13) || 1;
      setBands(Array.from({ length: 13 }, (_, i) => {
        let sum = 0;
        for (let j = 0; j < step; j++) sum += buf[i * step + j] || 0;
        return sum / step / 255;
      }));
      raf.current = requestAnimationFrame(tick);
    };
    tick();
  }, [send]);

  const startFile = useCallback(async (file, withSound = true) => {
    reset();
    // ใช้นาฬิกาของ AudioContext เป็นตัวเดียวกันทั้งการเล่นเสียงและการส่งเข้า websocket
    // สิ่งที่ได้ยินกับสิ่งที่ส่งไปจึงตรงกันเป๊ะ ไม่ดริฟต์แบบ setTimeout
    const ctx = new AudioContext();
    const buf = await ctx.decodeAudioData(await file.arrayBuffer());
    rate.current = buf.sampleRate;
    const data = buf.getChannelData(0);
    let player = null;
    if (withSound) {
      player = ctx.createBufferSource();
      player.buffer = buf; player.connect(ctx.destination);
    }
    const t0 = ctx.currentTime + 0.15;
    player?.start(t0);
    audio.current = { ctx, player };
    setMode("file");
    setPlay({ pos: 0, dur: buf.duration });

    let i = 0;
    const tick = () => {
      if (!audio.current.ctx) return;
      const due = (ctx.currentTime - t0) * rate.current;
      while (i < data.length && i < due) {
        send(data.subarray(i, Math.min(i + CHUNK, data.length)), ctx.currentTime - t0);
        i += CHUNK;
      }
      const pos = Math.max(0, Math.min(buf.duration, ctx.currentTime - t0));
      setPlay({ pos, dur: buf.duration });
      if (i >= data.length && pos >= buf.duration) { stop(); return; }
      raf.current = requestAnimationFrame(tick);
    };
    tick();
  }, [send, stop]);

  return { connected, info, sentences, interim, mode, bands, play, stats,
           startMic, startFile, stop, clear: reset };
}
