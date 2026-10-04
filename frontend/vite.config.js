import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // The backend only allows this origin (CORS), so never switch to another port silently.
  server: { port: 5173, strictPort: true },
});
