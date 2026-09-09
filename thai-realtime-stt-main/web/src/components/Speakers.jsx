/* แถบผู้พูด — ตั้งชื่อได้ ใช้ร่วมกันทั้งสองหน้า */
import { useEffect, useState } from "react";
import { colorOf, speakers } from "../lib/speakers";

/** re-render เมื่อชื่อหรือ session เปลี่ยน ไม่ว่าจะแก้จากคอมโพเนนต์ไหน */
export function useSpeakerNames() {
  const [, bump] = useState(0);
  useEffect(() => speakers.subscribe(() => bump(n => n + 1)), []);
  return speakers;
}

export function SpeakerBar({ counts }) {
  const s = useSpeakerNames();
  const ids = [...counts.keys()].sort((a, b) => a - b);
  return (
    <div className="spkbar">
      <span className="chip">
        <span className="lbl">session</span>
        <input defaultValue={s.session} style={{ width: "6rem" }}
               onChange={e => s.setSession(e.target.value)}
               title="สองจอที่ใช้ชื่อนี้ตรงกันจะใช้ชุดชื่อผู้พูดเดียวกัน" />
      </span>
      {ids.map(id => (
        <span className="chip" key={id}>
          <span className="sw" style={{ background: colorOf(id) }} />
          <input placeholder={`คน ${id}`} value={s.raw(id)}
                 onChange={e => s.set(id, e.target.value)} />
          <span className="lbl">{counts.get(id)}</span>
        </span>
      ))}
    </div>
  );
}

/** นับว่าผู้พูดแต่ละคนพูดกี่ประโยค ใช้ทั้งแสดงผลและสร้างแถบด้านบน */
export function countSpeakers(sentences) {
  const m = new Map();
  for (const s of sentences)
    if (s.speaker != null) m.set(s.speaker, (m.get(s.speaker) || 0) + 1);
  return m;
}
