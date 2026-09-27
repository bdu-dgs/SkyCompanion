import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    // Bind IPv4 explicitly. On some Windows setups, http://localhost:5173 resolves to
    // IPv6 (::1) while Vite only listened on IPv4 — use http://127.0.0.1:5173 in the browser.
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        ws: true,
      },
    },
  },
});
