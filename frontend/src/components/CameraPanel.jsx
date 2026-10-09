import { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Space, Spin, Switch } from 'antd';
import { useVideoStream } from '../hooks/useVideoStream.js';
import { useWebcamUpload } from '../hooks/useWebcamUpload.js';
import { Panel, StatusTag } from './ui.jsx';
import { STATUS_COLORS } from '../threat.js';

// Si `camera.streamUrl` est renseigné (flux MJPEG du Pi), on l'affiche ;
// sinon on dessine un faux flux sur un canvas, avec les détections en surimpression.
function MockFeed({ detections }) {
  const canvasRef = useRef(null);
  const detectionsRef = useRef(detections);
  detectionsRef.current = detections;

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    let raf;

    const draw = (time) => {
      const { width: W, height: H } = canvas;
      const grad = ctx.createLinearGradient(0, 0, 0, H);
      grad.addColorStop(0, '#0e1a22');
      grad.addColorStop(1, '#070b0f');
      ctx.fillStyle = grad;
      ctx.fillRect(0, 0, W, H);

      ctx.strokeStyle = 'rgba(255,216,59,0.07)';
      ctx.lineWidth = 1;
      for (let gx = 0; gx <= W; gx += 40) { ctx.beginPath(); ctx.moveTo(gx, 0); ctx.lineTo(gx, H); ctx.stroke(); }
      for (let gy = 0; gy <= H; gy += 40) { ctx.beginPath(); ctx.moveTo(0, gy); ctx.lineTo(W, gy); ctx.stroke(); }

      // ligne de balayage
      const sy = ((time / 20) % (H + 60)) - 30;
      const scan = ctx.createLinearGradient(0, sy - 30, 0, sy + 30);
      scan.addColorStop(0, 'rgba(255,216,59,0)');
      scan.addColorStop(0.5, 'rgba(255,216,59,0.10)');
      scan.addColorStop(1, 'rgba(255,216,59,0)');
      ctx.fillStyle = scan;
      ctx.fillRect(0, sy - 30, W, 60);

      for (const d of detectionsRef.current) {
        const { x, y, w, h } = d.bbox;
        const bx = x * W, by = y * H, bw = w * W, bh = h * H;
        // silhouette factice
        ctx.fillStyle = 'rgba(255,255,255,0.07)';
        ctx.beginPath();
        ctx.ellipse(bx + bw / 2, by + bh * 0.16, bw * 0.22, bh * 0.13, 0, 0, Math.PI * 2);
        ctx.rect(bx + bw * 0.2, by + bh * 0.3, bw * 0.6, bh * 0.7);
        ctx.fill();
        ctx.strokeStyle = STATUS_COLORS.danger;
        ctx.lineWidth = 2;
        ctx.strokeRect(bx, by, bw, bh);
        const tag = `${d.label} ${Math.round(d.confidence * 100)}%`;
        ctx.font = '600 13px ui-monospace, monospace';
        const tw = ctx.measureText(tag).width + 10;
        ctx.fillStyle = STATUS_COLORS.danger;
        ctx.fillRect(bx, by - 20, tw, 20);
        ctx.fillStyle = '#fff';
        ctx.fillText(tag, bx + 5, by - 6);
      }
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, []);

  return <canvas ref={canvasRef} width={640} height={480} className="feed" />;
}

// Flux de la webcam du PC (getUserMedia, fonctionne sur localhost ou en https).
function WebcamFeed({ onError }) {
  const videoRef = useRef(null);

  useEffect(() => {
    let stream;
    let cancelled = false;
    navigator.mediaDevices
      .getUserMedia({ video: { width: 640, height: 480 }, audio: false })
      .then((s) => {
        if (cancelled) return s.getTracks().forEach((t) => t.stop());
        stream = s;
        videoRef.current.srcObject = s;
      })
      .catch((e) => onError(e.name === 'NotAllowedError' ? 'Accès à la caméra refusé.' : `Caméra indisponible : ${e.message}`));
    return () => {
      cancelled = true;
      stream?.getTracks().forEach((t) => t.stop());
    };
  }, [onError]);

  return <video ref={videoRef} className="feed" autoPlay muted playsInline />;
}

// Aperçu du backend : YOLO tourne côté serveur (sur la caméra du backend ou sur les images envoyées par
// la webcam du navigateur). Chaque image arrive avec ses résultats (positions des carrés, silhouettes,
// menace) sur /ws/video, et React dessine les carrés rouges sur le canvas (voir drawOverlay.js).
const VISION_WAIT = {
  loading: 'Chargement du modèle YOLO…',
  waiting: 'En attente de la webcam du navigateur — activez « Webcam PC »',
  running: 'En attente de la vidéo…',
  error: 'Caméra / YOLO indisponible',
  stopped: 'Vision arrêtée',
};

function waitText(vision, canControl) {
  if (vision.state === 'waiting' && vision.source === 'push') return 'En attente de la caméra du Raspberry (camera_push.py)…';
  if (vision.state === 'waiting' && !canControl) return "En attente de la webcam du navigateur (un administrateur doit l'activer)";
  return VISION_WAIT[vision.state] ?? vision.state;
}

function VisionFeed({ vision, canControl }) {
  const canvasRef = useRef(null);
  const { hasFrame } = useVideoStream(canvasRef, vision.state === 'running' || vision.state === 'waiting');

  return (
    <>
      <canvas ref={canvasRef} className="feed feed-canvas" style={{ visibility: hasFrame ? 'visible' : 'hidden' }} />
      {!hasFrame && (
        <div className="feed-overlay">
          {vision.state !== 'error' && <Spin />}
          <span>{waitText(vision, canControl)}</span>
        </div>
      )}
    </>
  );
}

// `detections` vient du modèle IA (en différé). `vision.enabled` : le backend porte YOLO.
// Interrupteur « Webcam PC » : sans YOLO, il affiche la webcam dans le navigateur ; avec YOLO, il
// l'envoie au backend (useWebcamUpload) et la vidéo annotée revient dans le panneau.
// `canControl` : compte admin. Un agent (consultation seule) voit l'image mais ne peut pas changer la source vidéo
// ni envoyer sa webcam.
export default function CameraPanel({ camera, detections, vision, canControl = true }) {
  const yolo = Boolean(vision?.enabled);
  const remote = yolo && vision.source === 'push'; // VISION_SOURCE=push : images envoyées par le Raspberry
  // si le backend attend déjà la webcam du navigateur (VISION_SOURCE=browser), on l'active d'emblée
  const [webcam, setWebcam] = useState(() => canControl && yolo && vision.source === 'browser');
  const [error, setError] = useState(null);
  const persons = detections.filter((d) => d.label === 'person').length;

  const toggle = (on) => {
    setError(null);
    setWebcam(on);
  };
  const onWebcamError = useCallback((msg) => {
    setError(msg);
    setWebcam(false);
  }, []);
  useWebcamUpload(yolo && webcam, onWebcamError);

  return (
    <Panel
      title="Caméra"
      extra={
        <Space>
          {(yolo || !webcam) && (
            <StatusTag tone={persons ? 'danger' : 'ok'}>{persons ? `${persons} personne détectée` : 'RAS'}</StatusTag>
          )}
          {/* caméra distante (Raspberry) : ses images arrivent seules, la webcam du navigateur ne doit pas s'y ajouter */}
          {!remote && canControl && <Switch checked={webcam} onChange={toggle} checkedChildren="Webcam PC" unCheckedChildren="Webcam PC" />}
        </Space>
      }
    >
      <div className="feed-wrap">
        {yolo ? (
          <VisionFeed vision={vision} canControl={canControl} />
        ) : webcam ? (
          <WebcamFeed onError={onWebcamError} />
        ) : camera.streamUrl ? (
          <img className="feed" src={camera.streamUrl} alt="Flux caméra" />
        ) : (
          <MockFeed detections={detections} />
        )}
        <span className="feed-tag">
          {yolo
            ? `YOLO · ${{ browser: 'webcam navigateur', push: 'caméra du Raspberry' }[vision.source] ?? 'caméra backend'} · ${vision.fps} fps`
            : webcam
              ? 'WEBCAM PC'
              : `CAM-01 · ${camera.width}×${camera.height} · ${camera.fps} fps${camera.streamUrl ? '' : ' · MOCK'}`}
        </span>
      </div>
      {yolo && vision.state === 'error' && <Alert type="error" showIcon title={vision.error} />}
      {error && <Alert type="error" showIcon title={error} />}
    </Panel>
  );
}
