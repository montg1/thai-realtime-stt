/* ชื่อผู้พูด แยกตาม session
 *
 * เลข speaker ที่เซิร์ฟเวอร์ตั้งเริ่มนับ 0 ใหม่ทุก websocket connection เพราะ
 * SpeakerHandler ถูกสร้างต่อหนึ่งการเชื่อมต่อ "คน 0" ของสองแท็บจึงเป็นคนละคน
 * ถ้าเก็บชื่อไว้ key เดียวกันชื่อจะทับกันมั่วเวลาเปิดสองจอพร้อมกัน
 *
 * แยกด้วย sessionStorage ซึ่งแยกต่อแท็บโดยธรรมชาติ (รีเฟรชยังอยู่ ปิดแท็บแล้วหาย)
 * อยากให้สองจอใช้ชุดเดียวกันก็พิมพ์ชื่อ session ให้ตรงกัน หรือเปิดด้วย ?session=...
 */
const PREFIX = "diar_names:";

export const COLORS = ["#3fbf9f", "#5b9cf6", "#f2b155", "#f2555a", "#b98cf0",
                       "#3fc6d8", "#f28a55", "#9cc85a"];

export const colorOf = id => COLORS[id % COLORS.length];

function initSession() {
  const fromUrl = new URLSearchParams(location.search).get("session");
  if (fromUrl) { sessionStorage.setItem("diar_session", fromUrl); return fromUrl; }
  let s = sessionStorage.getItem("diar_session");
  if (!s) {
    s = "จอ-" + Math.random().toString(36).slice(2, 5).toUpperCase();
    sessionStorage.setItem("diar_session", s);
  }
  return s;
}

let session = initSession();
let names = read();
const subs = new Set();

function read() {
  try {
    return new Map(Object.entries(
      JSON.parse(localStorage.getItem(PREFIX + session) || "{}")));
  } catch { return new Map(); }
}

function notify() { subs.forEach(f => f()); }

export const speakers = {
  get session() { return session; },
  subscribe(fn) { subs.add(fn); return () => subs.delete(fn); },
  nameOf: id => names.get(String(id)) || `คน ${id}`,
  raw: id => names.get(String(id)) || "",

  set(id, v) {
    v = (v || "").trim();
    if (v) names.set(String(id), v); else names.delete(String(id));
    localStorage.setItem(PREFIX + session, JSON.stringify(Object.fromEntries(names)));
    notify();
  },

  /** สลับไปใช้ชุดชื่ออีกชุด ของเดิมยังอยู่ใน localStorage ไม่ได้ลบ */
  setSession(v) {
    v = (v || "").trim();
    if (!v || v === session) return;
    session = v;
    sessionStorage.setItem("diar_session", session);
    names = read();
    notify();
  },
};
