import { useState } from "react";
import { useStt } from "./hooks/useStt";
import Mic from "./pages/Mic";
import Prove from "./pages/Prove";

export default function App() {
  // สองหน้าใช้ useStt ตัวเดียวกัน สลับแท็บแล้ว websocket ไม่ขาด
  // และผู้พูดที่สะสมไว้ก็ไม่รีเซ็ต ต่างจากของเดิมที่เป็นคนละหน้า HTML
  const stt = useStt();
  const [tab, setTab] = useState("mic");
  const { connected, info } = stt;

  return (
    <>
      <header>
        <span className="brand">THAI <b>REALTIME STT</b></span>
        <nav>
          <button className={tab === "mic" ? "on" : ""} onClick={() => setTab("mic")}>ไมโครโฟน</button>
          <button className={tab === "prove" ? "on" : ""} onClick={() => setTab("prove")}>วัดผล</button>
        </nav>
        <span className="status">
          <span className={"dot" + (connected ? " ok" : "")} />
          {connected ? "เชื่อมต่อแล้ว" : "ไม่ได้เชื่อมต่อ"}
        </span>
        {info && (
          <span className="ver" title={"model: " + info.model}>
            v{info.version}{info.diarize ? " · diarize" : ""}
          </span>
        )}
      </header>
      {tab === "mic" ? <Mic stt={stt} /> : <Prove stt={stt} />}
    </>
  );
}
