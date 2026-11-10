import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// In development (`npm run dev`), the API is proxied to sensai-web: the UI talks to the real agent
// instead of falling back to the demo. SENSAI_API overrides the address (default: sensai-web on port 8000).
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
