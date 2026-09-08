/* หน้าพิสูจน์ว่าระบบตามทันเวลาจริง
 *
 * วัดจาก "เวลาในสตรีมเสียง" ไม่ใช่นาฬิกาเบราว์เซอร์:
 * ฝั่ง client รู้ว่าส่งเสียงไปแล้วกี่มิลลิวินาที (sentMs) ส่วนเซิร์ฟเวอร์บอกกลับมาว่า
 * ผลลัพธ์ก้อนนี้เป็นของเสียงถึงตำแหน่งไหน (audio_ms) ผลต่างคือหน่วงจริง
 * ซึ่งไม่ขึ้นกับว่าเครือข่ายหรือ event loop ของเบราว์เซอร์จะสะดุดตอนไหน
 *
 * ส่งด้วย sample rate เดิมของ AudioContext (ปกติ 48k) เหมือน client.js ทุกอย่าง
 * เพื่อให้ผ่านเส้นทาง resample ฝั่งเซิร์ฟเวอร์เหมือนการใช้งานจริง
 */
const q = new URLSearchParams(location.search);
const WS_URL = q.get("ws") || (location.protocol === "https:"
  ? `wss://${location.host}/ws`
  : `ws://${location.hostname}:${q.get("port") || "9005"}`);

const CHUNK = 2048;                  // เท่ากับ client.js
const COLORS = Speakers.COLORS;

const el = id => document.getElementById(id);
let socket = null, ctx = null, node = null, src = null, stream = null;
let running = false, sentSamples = 0, srcRate = 48000, t0 = 0;
let player = null, playCtx = null, playT0 = 0, playDur = 0, raf = 0;
let lags = [], rtFirst = null, points = [], speakers = new Map();

/* ชื่อผู้พูดอยู่ใน speakers.js แยกตาม session เพราะเลข speaker ของแต่ละแท็บ
 * มาจากคนละ websocket connection จึงไม่เกี่ยวข้องกัน ดูคำอธิบายในไฟล์นั้น */
const nameOf = id => Speakers.nameOf(id);
const setName = (id, v) => Speakers.set(id, v);
Speakers.onchange = () => {
  document.querySelectorAll(".spk[data-spk]").forEach(
    e => e.textContent = Speakers.nameOf(+e.dataset.spk));
  document.querySelectorAll("#spks input[data-spk]").forEach(
    e => e.value = Speakers.raw(+e.dataset.spk));
};

/* ---------------- websocket ---------------- */

function connect() {
  socket = new WebSocket(WS_URL);
  socket.binaryType = "arraybuffer";
  socket.onopen = () => { el("dot").className = "dot ok"; el("conn").textContent = "Connected"; };
  socket.onclose = () => { el("dot").className = "dot"; el("conn").textContent = "Disconnected"; };
  socket.onerror = () => { el("conn").textContent = "Connection failed"; };
  socket.onmessage = ev => {
    const d = JSON.parse(ev.data);
    const sentMs = sentSamples / srcRate * 1000;
    // audio_ms คือตำแหน่งในสตรีมที่ผลนี้ครอบคลุมถึง ที่เหลือคือเวลาที่ใช้ประมวลผล
    const lag = d.audio_ms == null ? null : (sentMs - d.audio_ms) / 1000;

    if (d.type === "hello") {
      // เวอร์ชันที่โชว์คือของ "เซิร์ฟเวอร์" ไม่ใช่ของไฟล์ที่เบราว์เซอร์โหลดมา
      // ถ้าสองอย่างไม่ตรงกันจะได้รู้ ไม่ใช่เดาว่ารันโค้ดล่าสุดอยู่
      el("ver").textContent = "v" + d.version + (d.diarize ? " · diarize" : "");
      el("ver").title = "server v" + d.version + "\nmodel: " + d.model;
      return;
    }
    if (d.type === "realtime") {
      el("interim").textContent = d.text;
      if (lag != null) {
        if (rtFirst === null) { rtFirst = lag; el("mRt").textContent = lag.toFixed(2) + "s"; }
        points.push({ x: d.audio_ms / 1000, y: lag, kind: "rt" });
        draw();
      }
    } else if (d.type === "fullSentence") {
      el("interim").textContent = "";
      addRow(d, lag);
      if (lag != null) {
        lags.push(lag);
        points.push({ x: d.audio_ms / 1000, y: lag, kind: "final" });
        updateStats();
        draw();
      }
    }
  };
}

/* ---------------- แสดงผล ---------------- */

function lagColor(v) { return v < 1 ? "var(--ok)" : v < 2 ? "var(--warn)" : "var(--bad)"; }

function addRow(d, lag) {
  const row = document.createElement("div");
  row.className = "row";
  if (lag != null) {
    const b = document.createElement("span");
    b.className = "lag";
    b.style.color = lagColor(lag);
    b.style.border = "1px solid " + lagColor(lag);
    b.textContent = lag.toFixed(2) + "s";
    row.appendChild(b);
  }
  if (d.speaker != null) {
    const c = COLORS[d.speaker % COLORS.length];
    const s = document.createElement("span");
    s.className = "spk";
    s.style.background = c; s.style.color = "#0b1020";
    s.dataset.spk = d.speaker;
    s.textContent = nameOf(d.speaker);
    s.title = "คลิกเพื่อตั้งชื่อ";
    s.onclick = () => {
      const inp = document.querySelector(`#spks input[data-spk="${d.speaker}"]`);
      if (inp) { inp.focus(); inp.select(); }
    };
    row.appendChild(s);
    speakers.set(d.speaker, (speakers.get(d.speaker) || 0) + 1);
    renderSpeakers();
  }
  const t = document.createElement("span");
  t.textContent = d.text;
  row.appendChild(t);
  el("log").appendChild(row);
  el("log").scrollTop = el("log").scrollHeight;
}

function renderSpeakers() {
  const box = el("spks");
  el("spkhint").style.display = speakers.size ? "none" : "";
  for (const [id, n] of [...speakers.entries()].sort((a, b) => a[0] - b[0])) {
    let row = box.querySelector(`.spkrow[data-spk="${id}"]`);
    if (!row) {
      row = document.createElement("div");
      row.className = "spkrow";
      row.dataset.spk = id;
      const sw = document.createElement("span");
      sw.className = "swatch";
      sw.style.background = COLORS[id % COLORS.length];
      const inp = document.createElement("input");
      inp.dataset.spk = id;
      inp.placeholder = "คน " + id;
      inp.value = Speakers.raw(id);
      inp.oninput = () => setName(id, inp.value);
      const cnt = document.createElement("span");
      cnt.className = "n";
      row.append(sw, inp, cnt);
      box.appendChild(row);
    }
    row.querySelector(".n").textContent = n + " ประโยค";
  }
}

function pct(a, p) { return a.length ? a.slice().sort((x, y) => x - y)[Math.min(a.length - 1, Math.floor(a.length * p))] : 0; }

function updateStats() {
  el("mLast").textContent = lags[lags.length - 1].toFixed(2) + "s";
  el("mP50").textContent = pct(lags, .5).toFixed(2) + "s";
  el("mP95").textContent = pct(lags, .95).toFixed(2) + "s";
  el("mMax").textContent = Math.max(...lags).toFixed(2) + "s";
  el("mN").textContent = lags.length;
}

function draw() {
  const c = el("chart"), dpr = devicePixelRatio || 1;
  const w = c.clientWidth, h = c.clientHeight;
  c.width = w * dpr; c.height = h * dpr;
  const g = c.getContext("2d"); g.scale(dpr, dpr);
  g.clearRect(0, 0, w, h);
  if (!points.length) return;

  const maxX = Math.max(10, ...points.map(p => p.x));
  const maxY = Math.max(2, ...points.map(p => p.y)) * 1.15;
  const X = v => v / maxX * (w - 34) + 30;
  const Y = v => h - 18 - v / maxY * (h - 26);

  g.strokeStyle = "#272b35"; g.lineWidth = 1; g.font = "10px sans-serif";
  g.fillStyle = "#8b93a7";
  for (let i = 0; i <= 4; i++) {
    const v = maxY * i / 4, y = Y(v);
    g.beginPath(); g.moveTo(30, y); g.lineTo(w - 4, y); g.stroke();
    g.fillText(v.toFixed(1) + "s", 2, y + 3);
  }
  // เส้นอ้างอิง 1 วินาที — ต่ำกว่านี้ถือว่าตามทันสบาย
  if (maxY > 1) {
    g.strokeStyle = "#4ade8055"; g.setLineDash([4, 4]);
    g.beginPath(); g.moveTo(30, Y(1)); g.lineTo(w - 4, Y(1)); g.stroke();
    g.setLineDash([]);
  }
  g.fillStyle = "#4ade80";
  for (const p of points) if (p.kind === "rt") g.fillRect(X(p.x) - 1, Y(p.y) - 1, 2, 2);

  const fin = points.filter(p => p.kind === "final");
  if (fin.length) {
    g.strokeStyle = "#60a5fa"; g.lineWidth = 1.5; g.beginPath();
    fin.forEach((p, i) => i ? g.lineTo(X(p.x), Y(p.y)) : g.moveTo(X(p.x), Y(p.y)));
    g.stroke();
    g.fillStyle = "#60a5fa";
    for (const p of fin) { g.beginPath(); g.arc(X(p.x), Y(p.y), 2.5, 0, 7); g.fill(); }
  }
}

/* ---------------- ส่งเสียง ---------------- */

function send(f32) {
  if (!socket || socket.readyState !== WebSocket.OPEN) return;
  const i16 = new Int16Array(f32.length);
  for (let i = 0; i < f32.length; i++)
    i16[i] = Math.max(-32768, Math.min(32767, f32[i] * 32768));
  const meta = new TextEncoder().encode(JSON.stringify({ sampleRate: srcRate }));
  const len = new ArrayBuffer(4);
  new DataView(len).setInt32(0, meta.byteLength, true);
  socket.send(new Blob([len, meta, i16.buffer]));
  sentSamples += f32.length;

  // ดริฟต์: ถ้าส่งตรงเวลาจริง เสียงที่ส่งไปต้องเท่ากับเวลาที่ผ่านไป
  // โหมดไฟล์ใช้นาฬิกาของ AudioContext ซึ่งเป็นตัวเดียวกับที่ขับเสียงที่ได้ยิน
  const elapsed = playCtx ? playCtx.currentTime - playT0 : (performance.now() - t0) / 1000;
  const drift = elapsed - sentSamples / srcRate;
  el("mDrift").textContent = (drift >= 0 ? "+" : "") + drift.toFixed(2) + "s";
  el("mDrift").style.color = Math.abs(drift) < 0.3 ? "var(--ok)" : "var(--warn)";
  el("mSent").textContent = (sentSamples / srcRate).toFixed(1) + "s";
}

function reset() {
  sentSamples = 0; lags = []; points = []; rtFirst = null; speakers.clear();
  el("log").innerHTML = ""; el("interim").textContent = "";
  el("spks").innerHTML = ""; el("spkhint").style.display = "";
  el("mRt").textContent = "–";
  ["mLast", "mP50", "mP95", "mMax"].forEach(k => el(k).textContent = "–");
  el("mN").textContent = "0";
  t0 = performance.now();
  draw();
}

async function startMic() {
  reset(); running = true;
  el("stop").disabled = false; el("mic").classList.add("on");
  stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  ctx = new AudioContext(); srcRate = ctx.sampleRate;
  src = ctx.createMediaStreamSource(stream);
  node = ctx.createScriptProcessor(CHUNK, 1, 1);
  node.onaudioprocess = e => running && send(e.inputBuffer.getChannelData(0));
  src.connect(node); node.connect(ctx.destination);
}

async function startFile(file) {
  reset(); running = true;
  el("stop").disabled = false;

  // ใช้ AudioContext เป็นนาฬิกาหลัก ทั้งการเล่นเสียงและการส่งเข้า websocket
  // เดินด้วยนาฬิกาเดียวกัน สิ่งที่ได้ยินกับสิ่งที่ส่งไปจึงตรงกันเป๊ะเสมอ
  playCtx = new AudioContext();
  const buf = await playCtx.decodeAudioData(await file.arrayBuffer());
  srcRate = buf.sampleRate;
  playDur = buf.duration;
  const data = buf.getChannelData(0);

  el("playbar").style.display = "";
  el("dur").textContent = fmt(playDur);

  if (el("play").checked) {
    player = playCtx.createBufferSource();
    player.buffer = buf;
    player.connect(playCtx.destination);
  }
  playT0 = playCtx.currentTime + 0.15;      // เผื่อเวลาให้ decoder ตั้งตัว
  if (player) player.start(playT0);

  let i = 0;
  const tick = () => {
    if (!running) return;
    const due = (playCtx.currentTime - playT0) * srcRate;
    while (i < data.length && i < due) {
      send(data.subarray(i, Math.min(i + CHUNK, data.length)));
      i += CHUNK;
    }
    const pos = Math.max(0, Math.min(playDur, playCtx.currentTime - playT0));
    el("pos").textContent = fmt(pos);
    el("bar").style.width = (pos / playDur * 100).toFixed(1) + "%";
    if (i >= data.length && pos >= playDur) { stopAll(true); return; }
    raf = requestAnimationFrame(tick);
  };
  tick();
}

function fmt(s) {
  const m = Math.floor(s / 60), r = Math.floor(s % 60);
  return m + ":" + String(r).padStart(2, "0");
}

function stopAll(keep) {
  running = false;
  if (raf) { cancelAnimationFrame(raf); raf = 0; }
  if (player) { try { player.stop(); } catch (e) {} player = null; }
  if (playCtx) { playCtx.close(); playCtx = null; }
  el("stop").disabled = true; el("mic").classList.remove("on");
  if (node) { node.disconnect(); node = null; }
  if (src) { src.disconnect(); src = null; }
  if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null; }
  if (ctx) { ctx.close(); ctx = null; }
  if (!keep) reset();
}

el("mic").onclick = () => running ? stopAll() : startMic();
el("stop").onclick = () => stopAll(true);
el("file").onchange = e => e.target.files[0] && startFile(e.target.files[0]);
addEventListener("resize", draw);

// ช่อง session — พิมพ์ชื่อเดียวกันสองจอ = ใช้ชุดชื่อผู้พูดร่วมกัน
el("sess").value = Speakers.session;
el("sess").onchange = () => Speakers.setSession(el("sess").value);

connect();
