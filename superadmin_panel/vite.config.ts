import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()], base: '/shirin/superadmin/',
  resolve: { dedupe: ['react', 'react-dom', '@tanstack/react-query'] },
  server: {
    port: 5185, host: '127.0.0.1', fs: { allow: ['..'] },
    proxy: { '/shirin/api': 'http://127.0.0.1:8083' },
  },
});
