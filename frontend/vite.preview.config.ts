import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/** Dev harness for the announcements card. Not part of the Home Assistant bundle. */
export default defineConfig({
  plugins: [react()],
  root: "preview",
  server: { port: 4177, strictPort: true },
});
