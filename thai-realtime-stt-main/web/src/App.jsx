import { useMemo, useState } from "react";
import { useStt } from "./hooks/useStt";
import { SpeakerBar, countSpeakers, useSpeakerNames } from "./components/Speakers";
import Mic from "./pages/Mic";
import Prove from "./pages/Prove";

export default function App() {
  // สองหน้าใช้ useStt ตัวเดียวกัน สลับแท็บแล้ว websocket ไม่ขาด
  // และผู้พูดที่สะสมไว้ก็ไม่รีเซ็ต ต่างจากของเดิมที่เป็นคนละหน้า HTML
  const stt = useStt();
  const [tab, setTab] = useState("mic");
  const [withSound, setWithSound] = useState(true);
  const names = useSpeakerNames();
  const { connected, info, sentences, mode, clear, startFile, startMic, stop } = stt;
  const counts = useMemo(() => countSpeakers(sentences), [sentences]);

  const copy = () => navigator.clipboard.writeText(
    sentences.map(s => (s.speaker != null ? names.nameOf(s.speaker) + ": " : "") + s.text)
             .join("\n"));

  const prove = tab === "prove";
  return (
    <>
      <header>
        <span className="brand">
          {prove ? <b>Real-time Speaker Diarization</b>
                 : <><b>Thai STT</b> · FastConformer-Transducer</>}
        </span>

        <span className="status">
          <span className={"dot" + (connected ? " ok" : "")} />
          {connected ? "Connected" : "Disconnected"}
        </span>
        {info && (
          <span className="status ver" title={"model: " + info.model}>
            v{info.version}{info.diarize ? " · diarize" : ""}
          </span>
        )}
        {!prove && (
          <span className="status">
            <span className={"dot" + (mode === "mic" ? " live" : "")} />
            {mode === "mic" ? "ไมค์เปิด" : "ไมค์ปิด"}
          </span>
        )}

        <span className="spacer" />
        <nav>
          <button className={"ghost" + (!prove ? " on" : "")}
                  onClick={() => setTab("mic")}>ไมโครโฟน</button>
          <button className={"ghost" + (prove ? " on" : "")}
                  onClick={() => setTab("prove")}>วัดผล</button>
        </nav>

        {/* หน้าวัดผลคุมทุกอย่างจาก header เหมือนหน้าเดิม ส่วนหน้าไมค์ใช้ปุ่มใหญ่ตรงกลาง */}
        {prove ? (
          <>
            <label className="ghost file">
              Select Audio File
              <input type="file" accept="audio/*" hidden
                     onChange={e => e.target.files[0] && startFile(e.target.files[0], withSound)} />
            </label>
            <button className={"ghost" + (mode === "mic" ? " on" : "")}
                    onClick={() => mode === "mic" ? stop() : startMic()}>
              🎤 Speak via Microphone
            </button>
            <button className="ghost" disabled={!mode} onClick={stop}>Stop</button>
            <label className="check">
              <input type="checkbox" checked={withSound}
                     onChange={e => setWithSound(e.target.checked)} /> Play Audio
            </label>
          </>
        ) : (
          <>
            <button className="ghost" disabled={!sentences.length} onClick={copy}>คัดลอก</button>
            <button className="ghost" disabled={!sentences.length} onClick={clear}>ล้าง</button>
          </>
        )}
      </header>

      {!prove && <SpeakerBar counts={counts} />}
      {prove ? <Prove stt={stt} counts={counts} /> : <Mic stt={stt} />}
    </>
  );
}
