/* หน้าพิสูจน์ว่าตามทันเวลาจริง — เล่นไฟล์ไปด้วย วัดหน่วงไปด้วย */
import { useEffect, useRef } from "react";
import { colorOf } from "../lib/speakers";
import { useSpeakerNames } from "../components/Speakers";

const fmt = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
const pct = (a, p) => a.length
  ? [...a].sort((x, y) => x - y)[Math.min(a.length - 1, Math.floor(a.length * p))] : 0;
const lagClass = v => (v < 1 ? "ok" : v < 2 ? "warn" : "bad");

export default function Prove({ stt, counts }) {
  const { sentences, interim, mode, play, stats } = stt;
  const names = useSpeakerNames();
  const canvas = useRef(null);

  useEffect(() => draw(canvas.current, stats.points), [stats.points]);

  const { lags } = stats;
  return (
    <div className="prove">
        <div className="col">
          {mode === "file" && (
            <div className="card">
              <h2>กำลังเล่น</h2>
              <div className="row-mid">
                <span className="pos">{fmt(play.pos)}</span>
                <div className="track">
                  <div style={{ width: (play.pos / (play.dur || 1) * 100) + "%" }} />
                </div>
                <span className="dim">{fmt(play.dur)}</span>
              </div>
              <p className="hint">
                ฟังไปด้วยแล้วดูข้อความด้านล่าง จะรู้สึกได้เองว่าหน่วงแค่ไหน
                ตัวเลขข้างประโยคคือหน่วงจริงของประโยคนั้น
              </p>
            </div>
          )}

          <div className="card">
            <h2>ความหน่วงเทียบเวลาในสตรีม</h2>
            <canvas ref={canvas} className="chart" />
            <p className="hint">
              แกนนอน = เวลาในไฟล์ แกนตั้ง = หน่วงกี่วินาที
              เส้นฟ้า = ประโยคสรุป จุดเขียว = ข้อความสด
              <b> เส้นแบน = ตามทันจริง เส้นไต่ขึ้น = ประมวลผลไม่ทันแล้วงานทบ</b>
            </p>
          </div>

          <div className="card">
            <h2>ผลถอดเสียง</h2>
            {interim && <p className="interim">{interim}</p>}
            {sentences.map((s, i) => (
              <div className="logrow" key={i}>
                {s.lag != null && (
                  <span className={"lag " + lagClass(s.lag)}>{s.lag.toFixed(2)}s</span>
                )}
                {s.speaker != null && (
                  <span className="spk" style={{ background: colorOf(s.speaker) }}>
                    {names.nameOf(s.speaker)}
                  </span>
                )}
                <span>{s.text}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="col side">
          <div className="card">
            <h2>ตัวเลขที่วัดได้</h2>
            <div className="stats">
              <Stat v={lags.length ? lags[lags.length - 1].toFixed(2) + "s" : "–"} k="หน่วงล่าสุด" />
              <Stat v={lags.length ? pct(lags, .5).toFixed(2) + "s" : "–"} k="กลาง (p50)" />
              <Stat v={lags.length ? pct(lags, .95).toFixed(2) + "s" : "–"} k="p95" />
              <Stat v={lags.length ? Math.max(...lags).toFixed(2) + "s" : "–"} k="แย่สุด" />
              <Stat v={stats.rtFirst != null ? stats.rtFirst.toFixed(2) + "s" : "–"} k="ข้อความสดแรก" />
              <Stat v={lags.length} k="ประโยค" />
            </div>
          </div>

          <div className="card">
            <h2>ความถูกต้องของการทดสอบ</h2>
            <div className="stats">
              <Stat v={(stats.drift >= 0 ? "+" : "") + stats.drift.toFixed(2) + "s"}
                    k="ดริฟต์การส่ง" cls={Math.abs(stats.drift) < 0.3 ? "ok" : "warn"} />
              <Stat v={stats.sent.toFixed(1) + "s"} k="เสียงที่ส่งไป" />
            </div>
            <p className="hint">
              ดริฟต์คือส่วนต่างระหว่างนาฬิกาจริงกับปริมาณเสียงที่ส่งไป ต้องใกล้ศูนย์
              ไม่งั้นแปลว่าส่งเร็ว/ช้ากว่าเวลาจริง แล้วตัวเลขหน่วงจะเชื่อไม่ได้
            </p>
          </div>

          <div className="card">
            <h2>ผู้พูดที่แยกได้</h2>
            <div className="spkrow">
              <span className="sw" style={{ background: "var(--text-3)" }} />
              <input defaultValue={names.session} placeholder="ชื่อ session"
                     title="สองจอที่ใช้ชื่อนี้ตรงกันจะใช้ชุดชื่อผู้พูดเดียวกัน"
                     onChange={e => names.setSession(e.target.value)} />
            </div>
            {[...counts.keys()].sort((a, b) => a - b).map(id => (
              <div className="spkrow" key={id}>
                <span className="sw" style={{ background: colorOf(id) }} />
                <input placeholder={`คน ${id}`} value={names.raw(id)}
                       onChange={e => names.set(id, e.target.value)} />
                <span className="n">{counts.get(id)} ประโยค</span>
              </div>
            ))}
            {!counts.size && (
              <p className="hint">ยังไม่มี — พอระบบเจอผู้พูดจะขึ้นที่นี่ให้ตั้งชื่อได้</p>
            )}
          </div>
        </div>
    </div>
  );
}

const Stat = ({ v, k, cls }) => (
  <div className="stat"><div className={"v " + (cls || "")}>{v}</div><div className="k">{k}</div></div>
);

function draw(c, points) {
  if (!c) return;
  const dpr = devicePixelRatio || 1, w = c.clientWidth, h = c.clientHeight;
  c.width = w * dpr; c.height = h * dpr;
  const g = c.getContext("2d"); g.scale(dpr, dpr); g.clearRect(0, 0, w, h);
  if (!points.length) return;

  const maxX = Math.max(10, ...points.map(p => p.x));
  const maxY = Math.max(2, ...points.map(p => p.y)) * 1.15;
  const X = v => v / maxX * (w - 34) + 30;
  const Y = v => h - 18 - v / maxY * (h - 26);

  g.font = "10px sans-serif";
  for (let i = 0; i <= 4; i++) {
    const v = maxY * i / 4, y = Y(v);
    g.strokeStyle = "#252e3d"; g.beginPath();
    g.moveTo(30, y); g.lineTo(w - 4, y); g.stroke();
    g.fillStyle = "#66738a"; g.fillText(v.toFixed(1) + "s", 2, y + 3);
  }
  if (maxY > 1) {   // เส้นอ้างอิง 1 วินาที ต่ำกว่านี้ถือว่าตามทันสบาย
    g.strokeStyle = "#3fbf9f55"; g.setLineDash([4, 4]);
    g.beginPath(); g.moveTo(30, Y(1)); g.lineTo(w - 4, Y(1)); g.stroke();
    g.setLineDash([]);
  }
  g.fillStyle = "#3fbf9f";
  for (const p of points) if (p.kind === "rt") g.fillRect(X(p.x) - 1, Y(p.y) - 1, 2, 2);

  const fin = points.filter(p => p.kind === "final");
  if (fin.length) {
    g.strokeStyle = "#5b9cf6"; g.lineWidth = 1.5; g.beginPath();
    fin.forEach((p, i) => i ? g.lineTo(X(p.x), Y(p.y)) : g.moveTo(X(p.x), Y(p.y)));
    g.stroke();
    g.fillStyle = "#5b9cf6";
    for (const p of fin) { g.beginPath(); g.arc(X(p.x), Y(p.y), 2.5, 0, 7); g.fill(); }
  }
}
