import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const apiPort = process.env.API_PORT ?? 4000;

const green = (text) => `\x1b[32m${text}\x1b[0m`;
const red = (text) => `\x1b[31m${text}\x1b[0m`;

// Affiche dans le terminal du front quand la liaison WebSocket avec le back est établie (vert) / fermée (rouge).
const logLink = (proxy) => {
  proxy.on('open', () => console.log(green(`[front] connecté au back (WebSocket /ws -> :${apiPort})`)));
  proxy.on('close', () => console.log(red('[front] connexion au back fermée')));
};

// Le front parle à l'API via le proxy : pas de CORS à gérer en dev.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': `http://localhost:${apiPort}`, // REST + photos d'intrusion (/api/captures)
      // vidéo annotée (/ws/video) et webcam du navigateur vers YOLO (/ws/camera) : binaire, sans log
      '^/ws/(video|camera)$': { target: `ws://localhost:${apiPort}`, ws: true },
      '^/ws$': { target: `ws://localhost:${apiPort}`, ws: true, configure: logLink }, // événements
    },
  },
});
