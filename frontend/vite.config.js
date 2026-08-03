import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // Public landing pages are server-rendered by FastAPI (crawlers don't run
      // JS). Everything else — including /chat/* — stays on the SPA.
      '/book': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
