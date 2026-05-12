import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // In dev, Vite proxies /api/* to FastAPI so we don't need nginx locally.
      // This is the dev-time equivalent of the nginx proxy_pass rule.
      '/api': 'http://localhost:8000',
    },
  },
})
