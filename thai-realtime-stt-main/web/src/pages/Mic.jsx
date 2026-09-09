/* หน้าใช้งานจริง — โครงเดียวกับ typhoon_client/index.html เดิมทุกอย่าง
 * ปุ่มไมค์ 76px กลางจอ มิเตอร์อยู่เหนือปุ่ม ป้ายบอกสถานะอยู่ใต้ปุ่ม
 */
import { useEffect, useMemo, useRef } from "react";
import { colorOf } from "../lib/speakers";
import { useSpeakerNames } from "../components/Speakers";

export default function Mic({ stt }) {
  const { sentences, interim, mode, bands, startMic, stop } = stt;
  const names = useSpeakerNames();
  const recording = mode === "mic";
  const sheet = useRef(null);

  useEffect(() => {
    const el = sheet.current?.parentElement;
    if (el) el.scrollTop = el.scrollHeight;
  }, [sentences, interim]);

  // กด Space เริ่ม/หยุดพูด เหมือนของเดิม แต่ไม่ดักตอนโฟกัสอยู่ในช่องกรอกชื่อ
  useEffect(() => {
    const onKey = e => {
      if (e.code !== "Space" || e.target.tagName === "INPUT") return;
      e.preventDefault();
      recording ? stop() : startMic();
    };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, [recording, startMic, stop]);

  return (
    <>
      <main>
        <div className="sheet" ref={sheet}>
          {!sentences.length && !interim && (
            <p className="hint">
              กดปุ่มไมโครโฟนด้านล่างเพื่อเริ่มพูด<br />
              <span style={{ fontSize: ".85em" }}>หรือกด <kbd>Space</kbd></span>
            </p>
          )}
          {sentences.map((s, i) => (
            <p className="sentence" key={i}
               style={s.speaker != null
                 ? { borderInlineStartColor: colorOf(s.speaker) } : undefined}>
              {s.speaker != null && (
                <span className="who" style={{ color: colorOf(s.speaker) }}>
                  {names.nameOf(s.speaker)}
                </span>
              )}
              {s.text}
            </p>
          ))}
          {interim && <p className="interim">{interim}</p>}
        </div>
      </main>

      <footer>
        <div className="meter">
          {bands.map((v, i) => (
            <i key={i} style={{
              height: Math.max(3, Math.round(v * 22)) + "px",
              background: v > 0.06 ? "var(--live)" : "var(--line)",
            }} />
          ))}
        </div>
        <div className="mic-wrap">
          <button className={"mic" + (recording ? " on" : "")}
                  aria-pressed={recording} aria-label={recording ? "หยุด" : "เริ่มพูด"}
                  onClick={() => recording ? stop() : startMic()}>
            <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <rect x="9" y="2" width="6" height="11" rx="3" />
              <path d="M5 10.5a7 7 0 0 0 14 0" />
              <path d="M12 17.5V21" />
            </svg>
          </button>
        </div>
        <span className="mic-label">{recording ? "กำลังฟัง" : "เริ่มพูด"}</span>
      </footer>
    </>
  );
}
