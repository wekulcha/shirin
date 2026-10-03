import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/shirin/',
  server: { port: 5183, host: '127.0.0.1', proxy: {
    '/shirin/api': 'http://127.0.0.1:8083',
    '/shirin/webhooks': 'http://127.0.0.1:8083',
  } },
})
