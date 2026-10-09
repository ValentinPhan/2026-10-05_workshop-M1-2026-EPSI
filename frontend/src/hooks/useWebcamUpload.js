import { useEffect } from 'react';
import { postJson } from '../api.js';

const FPS = 10; // images envoyées par seconde (= plafond VISION_FPS du backend ; c'est aussi le fps des clips vidéo)
const MAX_WIDTH = 640;
const JPEG_QUALITY = 0.7;
const MAX_BUFFERED_BYTES = 500_000; // si le réseau ou YOLO ne suit pas, on saute des images au lieu d'accumuler

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// Après le passage en mode navigateur, le backend relâche sa propre webcam : on réessaie quelques
// fois si elle est encore occupée.
async function openCamera(isCancelled) {
  for (let attempt = 0; ; attempt++) {
    try {
      return await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 }, audio: false });
    } catch (e) {
      if (e.name !== 'NotReadableError' || attempt >= 8 || isCancelled()) throw e;
      await sleep(500);
    }
  }
}

function describe(e) {
  if (e.name === 'NotAllowedError') return 'Accès à la caméra refusé.';
  if (e.name === 'NotReadableError') return 'Caméra occupée par un autre programme.';
  return e.message?.startsWith('Vision') ? e.message : `Caméra indisponible : ${e.message}`;
}

// Quand `active` : la webcam du navigateur envoie ses images (JPEG binaire) au backend sur /ws/camera,
// YOLO les traite, et la vidéo annotée revient par /ws/video (voir useVideoStream).
// À la désactivation, le backend reprend sa caméra.
export function useWebcamUpload(active, onError) {
  useEffect(() => {
    if (!active) return undefined;
    let cancelled = false;
    let modeSet = false;
    let stream;
    let ws;
    let timer;

    (async () => {
      try {
        await postJson('/api/vision/source', { mode: 'browser' }); // le backend relâche sa caméra
        modeSet = true;
        stream = await openCamera(() => cancelled);
        if (cancelled) return stream.getTracks().forEach((t) => t.stop());

        const video = document.createElement('video');
        video.muted = true;
        video.playsInline = true;
        video.srcObject = stream;
        await video.play();
        const canvas = document.createElement('canvas');
        const ctx = canvas.getContext('2d');

        const proto = location.protocol === 'https:' ? 'wss' : 'ws';
        ws = new WebSocket(`${proto}://${location.host}/ws/camera`);
        ws.onclose = () => !cancelled && onError('Connexion caméra avec le backend perdue.');

        timer = setInterval(() => {
          if (ws.readyState !== WebSocket.OPEN || ws.bufferedAmount > MAX_BUFFERED_BYTES || !video.videoWidth) return;
          const scale = Math.min(1, MAX_WIDTH / video.videoWidth);
          canvas.width = Math.round(video.videoWidth * scale);
          canvas.height = Math.round(video.videoHeight * scale);
          ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
          canvas.toBlob((blob) => blob && ws.readyState === WebSocket.OPEN && ws.send(blob), 'image/jpeg', JPEG_QUALITY);
        }, 1000 / FPS);
      } catch (e) {
        if (!cancelled) onError(describe(e));
      }
    })();

    return () => {
      cancelled = true;
      clearInterval(timer);
      ws?.close();
      stream?.getTracks().forEach((t) => t.stop());
      if (modeSet) postJson('/api/vision/source', { mode: 'default' }).catch(() => {});
    };
  }, [active, onError]);
}
