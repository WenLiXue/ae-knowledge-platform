import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    // 与后端 API 保持同一 host（127.0.0.1），确保 SameSite=Lax 会话 Cookie 能同站携带
    host: "127.0.0.1",
    port: 5173,
  },
});
