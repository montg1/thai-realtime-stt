/* โปรโตคอลสาย — ต้องตรงกับ api/main.py เป๊ะ
 *
 * ขาขึ้น : [4 ไบต์ int32 LE ความยาว metadata][metadata JSON][PCM int16 LE mono]
 * ขาลง   : JSON {type: hello|realtime|fullSentence, ...}
 *
 * แนบ sampleRate ไปทุกก้อนแทนที่จะบอกครั้งเดียวตอน handshake เพราะเป็นสตรีมสด
 * ไม่มีจังหวะ "เริ่มไฟล์" ให้ประกาศ และถ้าต่อใหม่กลางคันทุกก้อนก็อธิบายตัวเองได้
 */
export const CHUNK = 2048;          // ~43ms @48k

export function encodeChunk(float32, sampleRate) {
  const i16 = new Int16Array(float32.length);
  for (let i = 0; i < float32.length; i++)
    i16[i] = Math.max(-32768, Math.min(32767, float32[i] * 32768));
  const meta = new TextEncoder().encode(JSON.stringify({ sampleRate }));
  const len = new ArrayBuffer(4);
  new DataView(len).setInt32(0, meta.byteLength, true);
  return new Blob([len, meta, i16.buffer]);
}

/** https -> wss บน origin เดียวกัน (Caddy พร็อกซีให้), http -> ต่อตรงตามพอร์ต */
export function wsUrl() {
  const q = new URLSearchParams(location.search);
  if (q.get("ws")) return q.get("ws");
  if (location.protocol === "https:") return `wss://${location.host}/ws`;
  // dev ผ่าน vite ใช้ /ws ที่ proxy ไว้แล้ว ส่วนเปิดตรง ๆ ให้ระบุพอร์ต API
  const port = q.get("port");
  return port ? `ws://${location.hostname}:${port}/v1/stream`
              : `ws://${location.host}/ws`;
}
