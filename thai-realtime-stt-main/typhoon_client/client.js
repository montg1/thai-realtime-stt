/* Typhoon ASR browser client.
   Wire protocol (unchanged): [4-byte LE metadata length][metadata JSON][int16 PCM] */

// ?port=9001 ชี้ไป RealtimeSTT, ?port=9002 ชี้ไป Typhoon — สองระบบใช้โปรโตคอลเดียวกัน
// เปิดผ่าน https: ใช้ /ws บน origin เดียวกัน (Caddy พร็อกซีต่อให้) จะได้ยอมรับ cert ครั้งเดียว
// ถ้าแยกพอร์ต wss เบราว์เซอร์จะเงียบ ๆ ปฏิเสธ cert ของพอร์ตที่สองโดยไม่ถามอะไรเลย
// เปิดผ่าน http: ต่อตรงตาม host ของหน้าเว็บ (ผ่าน ssh tunnel ก็ยังได้ เพราะเป็น localhost อยู่แล้ว)
const _q = new URLSearchParams(location.search);
const WS_URL = _q.get("ws") || (location.protocol === "https:"
  ? `wss://${location.host}/ws`
  : `ws://${location.hostname}:${_q.get("port") || "9002"}`);
const BUFFER_SIZE = 2048;          // ~43ms @48k — was 256 (~5ms, 200 msgs/sec)
const METER_BARS = 13;
const TAIL_SILENCE_MS = 900;       // let the server's VAD close the last sentence

const el = {
  dotServer: document.getElementById("dotServer"),
  txtServer: document.getElementById("txtServer"),
  dotMic: document.getElementById("dotMic"),
  txtMic: document.getElementById("txtMic"),
  sentences: document.getElementById("sentences"),
  interim: document.getElementById("interim"),
  hint: document.getElementById("hint"),
  meter: document.getElementById("meter"),
  btnMic: document.getElementById("btnMic"),
  micLabel: document.getElementById("micLabel"),
  btnClear: document.getElementById("btnClear"),
  btnCopy: document.getElementById("btnCopy"),
  spkbar: document.getElementById("spkbar"),
};

/* ---------------- ผู้พูด ---------------- */

const spkSeen = new Map();
const spkColor = id => Speakers.color(id);
const spkName = id => Speakers.nameOf(id);
const setSpkName = (id, v) => Speakers.set(id, v);
// ชื่อแยกตาม session เพราะเลข speaker ของแต่ละแท็บมาจากคนละ connection
Speakers.onchange = () => {
  document.querySelectorAll(".who[data-spk]").forEach(
    e => e.textContent = Speakers.nameOf(+e.dataset.spk));
  document.querySelectorAll(".spkbar input[data-spk]").forEach(
    e => e.value = Speakers.raw(+e.dataset.spk));
};

function renderSpkBar() {
  for (const [id, n] of [...spkSeen.entries()].sort((a, b) => a[0] - b[0])) {
    let chip = el.spkbar.querySelector(`.chip[data-spk="${id}"]`);
    if (!chip) {
      chip = document.createElement("span");
      chip.className = "chip";
      chip.dataset.spk = id;
      const sw = document.createElement("span");
      sw.className = "sw";
      sw.style.background = spkColor(id);
      const inp = document.createElement("input");
      inp.placeholder = "คน " + id;
      inp.dataset.spk = id;
      inp.value = Speakers.raw(id);
      inp.oninput = () => setSpkName(id, inp.value);
      const lbl = document.createElement("span");
      lbl.className = "lbl";
      chip.append(sw, inp, lbl);
      el.spkbar.appendChild(chip);
    }
    chip.querySelector(".lbl").textContent = n;
  }
}

const bars = [];
for (let i = 0; i < METER_BARS; i++) {
  const b = document.createElement("i");
  el.meter.appendChild(b);
  bars.push(b);
}

let socket = null;
let serverReady = false;
let recording = false;
let audioCtx = null, source = null, processor = null, analyser = null, stream = null;
let sentences = [];
let rafId = null;

/* ---------------- websocket ---------------- */

function setServerState(ok, label) {
  serverReady = ok;
  el.dotServer.className = "dot" + (ok ? " ok" : "");
  el.txtServer.textContent = label;
  // ไม่ disable ปุ่มไมค์ตามสถานะเซิร์ฟเวอร์ เดิมพอ wss ต่อไม่ติดปุ่มจะกดไม่ลง
  // แล้วดูไม่ออกว่าเป็นเพราะไมค์หรือเพราะเน็ต — ให้กดได้แล้วบอกสาเหตุแทน
  el.btnMic.disabled = false;
  if (!ok && recording) el.txtMic.textContent = "ไมค์ทำงาน แต่ส่งไม่ได้ — เซิร์ฟเวอร์หลุด";
}

function connect() {
  socket = new WebSocket(WS_URL);
  socket.onopen = () => setServerState(true, "เชื่อมต่อแล้ว");
  socket.onclose = () => {
    setServerState(false, "ไม่ได้เชื่อมต่อ");
    if (recording) stopRecording();
    setTimeout(connect, 3000);
  };
  socket.onerror = () => setServerState(false, "เชื่อมต่อไม่ได้");
  socket.onmessage = (event) => {
    let data;
    try { data = JSON.parse(event.data); } catch { return; }
    if (data.type === "hello") {
      const v = document.getElementById("ver");
      v.textContent = "v" + data.version + (data.diarize ? " · diarize" : "");
      v.title = "server v" + data.version + "\nmodel: " + data.model;
      return;
    }
    if (data.type === "realtime") {
      showInterim(data.text);
    } else if (data.type === "fullSentence") {
      showInterim("");
      addSentence(data.text, data.speaker);
    }
  };
}

/* ---------------- transcript ---------------- */

function showInterim(text) {
  el.interim.textContent = text || "";
  if (text) {
    const caret = document.createElement("span");
    caret.className = "caret";
    el.interim.appendChild(caret);
  }
  scrollDown();
}

function addSentence(text, speaker) {
  if (!text) return;
  sentences.push({ text, speaker });
  const p = document.createElement("p");
  p.className = "sentence";
  if (speaker != null) {
    p.style.borderInlineStartColor = spkColor(speaker);
    const w = document.createElement("span");
    w.className = "who";
    w.dataset.spk = speaker;
    w.style.color = spkColor(speaker);
    w.textContent = spkName(speaker);
    p.appendChild(w);
    spkSeen.set(speaker, (spkSeen.get(speaker) || 0) + 1);
    renderSpkBar();
  }
  p.appendChild(document.createTextNode(text));
  el.sentences.appendChild(p);
  el.hint.style.display = "none";
  el.btnClear.disabled = false;
  el.btnCopy.disabled = false;
  scrollDown();
}

function scrollDown() {
  const main = document.querySelector("main");
  main.scrollTop = main.scrollHeight;
}

el.btnClear.addEventListener("click", () => {
  sentences = [];
  spkSeen.clear();
  el.spkbar.querySelectorAll(".chip[data-spk]").forEach(c => c.remove());
  el.sentences.textContent = "";
  showInterim("");
  el.hint.style.display = "";
  el.btnClear.disabled = true;
  el.btnCopy.disabled = true;
});

el.btnCopy.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(sentences.map(
      s => (s.speaker != null ? spkName(s.speaker) + ": " : "") + s.text).join("\n"));
    el.btnCopy.textContent = "คัดลอกแล้ว";
    setTimeout(() => { el.btnCopy.textContent = "คัดลอก"; }, 1400);
  } catch {
    el.btnCopy.textContent = "คัดลอกไม่ได้";
    setTimeout(() => { el.btnCopy.textContent = "คัดลอก"; }, 1600);
  }
});

/* ---------------- level meter ---------------- */

function drawMeter() {
  if (!analyser) return;
  const buf = new Uint8Array(analyser.frequencyBinCount);
  analyser.getByteFrequencyData(buf);
  const step = Math.floor(buf.length / METER_BARS) || 1;
  for (let i = 0; i < METER_BARS; i++) {
    let sum = 0;
    for (let j = 0; j < step; j++) sum += buf[i * step + j] || 0;
    const v = sum / step / 255;
    const h = Math.max(3, Math.round(v * 22));
    bars[i].style.height = h + "px";
    bars[i].style.background = v > 0.06 ? "var(--live)" : "var(--line)";
  }
  rafId = requestAnimationFrame(drawMeter);
}

function resetMeter() {
  if (rafId) cancelAnimationFrame(rafId);
  rafId = null;
  bars.forEach((b) => { b.style.height = "3px"; b.style.background = "var(--line)"; });
}

/* ---------------- recording ---------------- */

function sendChunk(int16, sampleRate) {
  if (!socket || socket.readyState !== WebSocket.OPEN) return;
  const meta = new TextEncoder().encode(JSON.stringify({ sampleRate }));
  const len = new ArrayBuffer(4);
  new DataView(len).setInt32(0, meta.byteLength, true);
  socket.send(new Blob([len, meta, int16.buffer]));
}

async function startRecording() {
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (e) {
    el.dotMic.className = "dot";
    el.txtMic.textContent = "ไม่ได้รับสิทธิ์ไมค์";
    return;
  }
  audioCtx = new AudioContext();
  source = audioCtx.createMediaStreamSource(stream);
  analyser = audioCtx.createAnalyser();
  analyser.fftSize = 128;
  processor = audioCtx.createScriptProcessor(BUFFER_SIZE, 1, 1);

  source.connect(analyser);
  source.connect(processor);
  processor.connect(audioCtx.destination);

  processor.onaudioprocess = (e) => {
    if (!recording) return;
    const input = e.inputBuffer.getChannelData(0);
    const out = new Int16Array(input.length);
    for (let i = 0; i < input.length; i++) {
      out[i] = Math.max(-32768, Math.min(32767, input[i] * 32768));
    }
    sendChunk(out, audioCtx.sampleRate);
  };

  recording = true;
  el.btnMic.classList.add("on");
  el.btnMic.setAttribute("aria-pressed", "true");
  el.btnMic.setAttribute("aria-label", "หยุดพูด");
  el.micLabel.textContent = "หยุด";
  el.dotMic.className = "dot live";
  el.txtMic.textContent = "กำลังฟัง";
  el.hint.style.display = "none";
  drawMeter();
}

function stopRecording() {
  const rate = audioCtx ? audioCtx.sampleRate : 48000;
  recording = false;

  // flush trailing silence so the server's VAD finalizes the last utterance
  if (socket && socket.readyState === WebSocket.OPEN) {
    const n = Math.round((rate * TAIL_SILENCE_MS) / 1000);
    sendChunk(new Int16Array(n), rate);
  }

  if (processor) { processor.disconst sess = document.getElementById("sess");
sess.value = Speakers.session;
sess.onchange = () => Speakers.setSession(sess.value);

connect(); processor.onaudioprocess = null; }
  if (source) source.disconnect();
  if (analyser) analyser.disconnect();
  if (stream) stream.getTracks().forEach((t) => t.stop());
  if (audioCtx) audioCtx.close();
  processor = source = analyser = stream = audioCtx = null;

  el.btnMic.classList.remove("on");
  el.btnMic.setAttribute("aria-pressed", "false");
  el.btnMic.setAttribute("aria-label", "เริ่มพูด");
  el.micLabel.textContent = "เริ่มพูด";
  el.dotMic.className = "dot";
  el.txtMic.textContent = "ไมค์ปิด";
  resetMeter();
}

function toggle() {
  if (!serverReady) return;
  recording ? stopRecording() : startRecording();
}

el.btnMic.addEventListener("click", toggle);

document.addEventListener("keydown", (e) => {
  if (e.code !== "Space") return;
  const t = e.target;
  if (t instanceof HTMLButtonElement || t instanceof HTMLInputElement) return;
  e.preventDefault();
  toggle();
});

resetMeter();
setServerState(false, "กำลังเชื่อมต่อ");
connect();
