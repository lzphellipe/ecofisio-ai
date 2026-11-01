import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// O dev server sobe em 5173 (origem já liberada no CORS da API).
// Aponte para a API com VITE_API_URL (padrão http://localhost:8080).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
});
