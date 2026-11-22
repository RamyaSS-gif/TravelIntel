
import { defineConfig } from "vite";

export default defineConfig({
  server: {
    host: "0.0.0.0",
    allowedHosts: ["desktop-9e422h3.tail16b4c2.ts.net"],
    proxy: {
      "/api": "http://127.0.0.1:8765",
    },
  },
});
