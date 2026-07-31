import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

const API_PROXY = process.env.API_PROXY || 'http://127.0.0.1:8099';

export default defineConfig({
  plugins: [svelte()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': API_PROXY,
    },
  },
  build: {
    outDir: '../hifi_detector/web/static',
    emptyOutDir: true,
  },
});
