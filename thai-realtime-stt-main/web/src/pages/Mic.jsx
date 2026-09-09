/* หน้าใช้งานจริง — กดไมค์แล้วพูด */
import { useMemo } from "react";
import { colorOf } from "../lib/speakers";
import { SpeakerBar, countSpeakers, useSpeakerNames } from "../components/Speakers";

const BARS = 13;

export default function Mic({ stt }) {
  const { connected, sentences, interim, mode, level, startMic, stop, clear } = stt;
  const names = useSpeakerNames();
  const counts = useMemo(() => countSpeakers(sentences), [sentences]);
  const recording = mode === "mic";

  const copy = () => navigator.clipboard.writeText(
    sentences.map(s => (s.speaker != null ? names.nameOf(s.speaker) + ": " : "") + s.text)
             .join("\n"));

  return (
    <>
      <SpeakerBar counts={counts} />
      <main className="scroll">
        {!sentences.length && !interim && (
          <p className="hint">กดปุ่มไมโครโฟนด้านล่างเพื่อเริ่มพูด</p>
        )}
        {sentences.map((s, i) => (
          <p className="sentence" key={i}
             style={s.speaker != null ? { borderInlineStartColor: colorOf(s.speaker) } : undefined}>
            {s.speaker != null && (
              <span className="who" style={{ color: colorOf(s.speaker) }}>
                {names.nameOf(s.speaker)}
              </span>
            )}
            {s.text}
          </p>
        ))}
        {interim && <p className="interim">{interim}<span className="caret" /></p>}
      </main>

      <footer>
        <div className="meter">
          {Array.from({ length: BARS }, (_, i) => {
            // แต่ละแท่งไวต่างกันเล็กน้อย ให้ดูเป็นสเปกตรัมไม่ใช่ก้อนเดียวขยับพร้อมกัน
            const h = Math.max(3, Math.round(level * 22 * (0.6 + (i % 5) * 0.2)));
            return <i key={i} style={{ height: h + "px",
                     background: recording && level > 0.04 ? "var(--live)" : "var(--line)" }} />;
          })}
        </div>
        <button className={"mic" + (recording ? " on" : "")}
                onClick={() => recording ? stop() : startMic()}>
          {recording ? "■" : "🎤"}
        </button>
        <span className="mic-label">{recording ? "หยุด" : "เริ่มพูด"}</span>
        <div className="actions">
          <button className="ghost" disabled={!sentences.length} onClick={copy}>คัดลอก</button>
          <button className="ghost" disabled={!sentences.length} onClick={clear}>ล้าง</button>
        </div>
        {!connected && <span className="warn">เซิร์ฟเวอร์หลุด — ไมค์ยังทำงานแต่ส่งไม่ได้</span>}
      </footer>
    </>
  );
}
