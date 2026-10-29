import { defineConfig } from 'vite';
import repos from './src/repos.js';
export default defineConfig({ server: { port: 5174, strictPort: true, proxy: { '/api/demos': {
  target: 'http://127.0.0.1:8000', rewrite: path => path.replace('/api/demos', '/demos'),
}, ...Object.fromEntries(repos.map(repo => [`/api/repos/${repo.id}`, {
  target: `http://127.0.0.1:${repo.port}`,
  rewrite: path => path.replace(`/api/repos/${repo.id}`, '/api'),
}])) } } });
