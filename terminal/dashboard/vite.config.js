import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 3000,
    allowedHosts: ['terminal.botcave.dev'],
    proxy: {
      '/api': 'http://localhost:8090'
    }
  }
})
