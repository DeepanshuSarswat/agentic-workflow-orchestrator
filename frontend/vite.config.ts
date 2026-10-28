import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// /api/* is proxied to FastAPI, so the browser never deals with CORS in dev.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": { target: "http://localhost:8000", rewrite: (p) => p.replace(/^\/api/, "") },
    },
  },
});
