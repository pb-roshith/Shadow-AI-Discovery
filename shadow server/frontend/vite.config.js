import { defineConfig, loadEnv } from 'vite';
import tailwindcss from '@tailwindcss/vite';
export default defineConfig(({ mode }) => { const env = loadEnv(mode, process.cwd(), ''); return { plugins: [tailwindcss()], server: { host: '127.0.0.1', port: 5173, strictPort: true, proxy: Object.fromEntries(['/discovery','/runs','/signals','/candidates','/issues','/reference','/demo','/config','/health','/scenarios','/ai','/inventory','/audit'].map(path => [path, env.BACKEND_URL || 'http://127.0.0.1:8000'])) } }; });
