import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// En développement (`npm run dev`), l'API est relayée vers sensai-web : l'interface parle au vrai agent
// au lieu de retomber sur la démonstration. SENSAI_API change l'adresse (défaut : port 8000 de sensai-web).
declare const process: { env: Record<string, string | undefined> }
const api = process.env.SENSAI_API ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': { target: api, changeOrigin: false },
      '/share': { target: api, changeOrigin: false },
    },
  },
  test: { environment: 'jsdom', globals: true, setupFiles: ['./tests/setup.ts'] },
})
