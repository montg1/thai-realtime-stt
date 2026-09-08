/* ชื่อผู้พูด แยกตาม session — ใช้ร่วมกันทั้งหน้าไมค์และหน้าวัดผล
 *
 * ทำไมต้องแยก: แต่ละแท็บเปิด websocket ของตัวเอง และเซิร์ฟเวอร์สร้าง SpeakerHandler
 * ใหม่ต่อหนึ่งการเชื่อมต่อ เลข speaker จึงเริ่มนับ 0 ใหม่ทุกแท็บและไม่เกี่ยวข้องกันเลย
 * "คน 0" ของจอซ้ายกับจอขวาเป็นคนละคน ถ้าเก็บชื่อไว้ key เดียวกันชื่อจะทับกันมั่ว
 *
 * ค่าเริ่มต้นแยกต่อแท็บด้วย sessionStorage (ปิดแท็บแล้วหาย แต่รีเฟรชยังอยู่)
 * ถ้าอยากให้สองจอใช้ชุดชื่อเดียวกันจริง ๆ ก็พิมพ์ชื่อ session ให้ตรงกัน
 * หรือเปิดด้วย ?session=ชื่อห้อง
 */
(function (global) {
  const PREFIX = "diar_names:";
  const q = new URLSearchParams(location.search);

  function initSession() {
    const fromUrl = q.get("session");
    if (fromUrl) { sessionStorage.setItem("diar_session", fromUrl); return fromUrl; }
    let s = sessionStorage.getItem("diar_session");
    if (!s) {
      s = "จอ-" + Math.random().toString(36).slice(2, 5).toUpperCase();
      sessionStorage.setItem("diar_session", s);
    }
    return s;
  }

  let session = initSession();
  let names = load();

  function load() {
    try {
      return new Map(Object.entries(
        JSON.parse(localStorage.getItem(PREFIX + session) || "{}")));
    } catch { return new Map(); }
  }

  function save() {
    localStorage.setItem(PREFIX + session, JSON.stringify(Object.fromEntries(names)));
  }

  global.Speakers = {
    COLORS: ["#3fbf9f", "#5b9cf6", "#f2b155", "#f2555a", "#b98cf0",
             "#3fc6d8", "#f28a55", "#9cc85a"],
    color(id) { return this.COLORS[id % this.COLORS.length]; },
    get session() { return session; },
    nameOf(id) { return names.get(String(id)) || ("คน " + id); },
    raw(id) { return names.get(String(id)) || ""; },

    set(id, v) {
      v = (v || "").trim();
      if (v) names.set(String(id), v); else names.delete(String(id));
      save();
      this.onchange && this.onchange();
    },

    /** เปลี่ยน session = สลับไปใช้ชุดชื่ออีกชุด ของเดิมยังอยู่ ไม่ได้ลบ */
    setSession(v) {
      v = (v || "").trim();
      if (!v || v === session) return;
      session = v;
      sessionStorage.setItem("diar_session", session);
      names = load();
      this.onchange && this.onchange();
    },

    onchange: null,
  };
})(window);
