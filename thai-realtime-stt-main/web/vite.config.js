import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// dev: vite เสิร์ฟที่ 5173 แล้ว proxy /v1 กับ /ws ไปที่ API จะได้ไม่ติด CORS
// prod: ไฟล์ static ถูก Caddy เสิร์ฟ ซึ่งอยู่ origin เดียวกับ API อยู่แล้ว
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    proxy: {
      "/v1": { target: "http://localhost:8000", changeOrigin: true },
      "/ws": { target: "ws://localhost:8000", ws: true,
               rewrite: p => p.replace(/^\/ws/, "/v1/stream") },
    },
  },
});
