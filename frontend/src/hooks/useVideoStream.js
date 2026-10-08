import { useEffect, useState } from 'react';
import { AUTH_EXPIRED } from '../api.js';
import { drawFrame } from '../components/drawOverlay.js';

// Reçoit sur /ws/video l'image de la caméra AVEC ses résultats YOLO (une image par message binaire) et les
// dessine sur le canvas `canvasRef` : carrés rouges, silhouettes, menace. Message :
//   [4 octets : taille N de l'en-tête, big-endian] [N octets : JSON {ts, width, height, annotated, detections, threat}] [JPEG]
// Le dessin est fait directement sur le canvas (pas d'état React par image : ~10 images/s sans re-render).
// Reconnexion automatique (backoff plafonné à 5 s).
export function useVideoStream(canvasRef, active) {
  const [connected, setConnected] = useState(false);
  const [hasFrame, setHasFrame] = useState(false);

  useEffect(() => {
    if (!active) return undefined;
    let ws;
    let timer;
    let retry = 0;
    let closed = false;
    let decoding = false; // si le décodage d'une image n'est pas fini, on saute la suivante (pas de retard cumulé)

    const connect = () => {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws';
      ws = new WebSocket(`${proto}://${location.host}/ws/video`);
      ws.binaryType = 'arraybuffer';

      ws.onopen = () => {
        retry = 0;
        setConnected(true);
      };

      ws.onmessage = async (event) => {
        const canvas = canvasRef.current;
        if (!canvas || decoding) return;
        decoding = true;
        try {
          const headerSize = new DataView(event.data).getUint32(0);
          const meta = JSON.parse(new TextDecoder().decode(new Uint8Array(event.data, 4, headerSize)));
          const bitmap = await createImageBitmap(new Blob([event.data.slice(4 + headerSize)], { type: 'image/jpeg' }));
          drawFrame(canvas, bitmap, meta);
          bitmap.close();
          setHasFrame(true);
        } catch {
          // image ou en-tête corrompu : on attend la suivante
        } finally {
          decoding = false;
        }
      };

      ws.onclose = (event) => {
        setConnected(false);
        setHasFrame(false);
        if (event.code === 4401) {
          closed = true;
          window.dispatchEvent(new Event(AUTH_EXPIRED)); // session refusée : retour à la page de connexion
          return;
        }
        if (!closed) timer = setTimeout(connect, Math.min(5000, 500 * 2 ** retry++));
      };
    };

    connect();
    return () => {
      closed = true;
      clearTimeout(timer);
      ws?.close();
      setConnected(false);
      setHasFrame(false);
    };
  }, [canvasRef, active]);

  return { connected, hasFrame };
}
