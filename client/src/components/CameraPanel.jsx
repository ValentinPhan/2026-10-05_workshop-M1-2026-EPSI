import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Space, Switch } from 'antd';
import { Panel, StatusTag } from './ui.jsx';

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

      ctx.strokeStyle = 'rgba(80,200,220,0.07)';
      ctx.lineWidth = 1;
      for (let gx = 0; gx <= W; gx += 40) { ctx.beginPath(); ctx.moveTo(gx, 0); ctx.lineTo(gx, H); ctx.stroke(); }
      for (let gy = 0; gy <= H; gy += 40) { ctx.beginPath(); ctx.moveTo(0, gy); ctx.lineTo(W, gy); ctx.stroke(); }

      // ligne de balayage
      const sy = ((time / 20) % (H + 60)) - 30;
      const scan = ctx.createLinearGradient(0, sy - 30, 0, sy + 30);
      scan.addColorStop(0, 'rgba(80,200,220,0)');
      scan.addColorStop(0.5, 'rgba(80,200,220,0.10)');
      scan.addColorStop(1, 'rgba(80,200,220,0)');
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
        ctx.strokeStyle = '#ff5a5f';
        ctx.lineWidth = 2;
        ctx.strokeRect(bx, by, bw, bh);
        const tag = `${d.label} ${Math.round(d.confidence * 100)}%`;
        ctx.font = '600 13px ui-monospace, monospace';
        const tw = ctx.measureText(tag).width + 10;
        ctx.fillStyle = '#ff5a5f';
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

// `detections` vient du modèle IA (en différé) ; la caméra du Pi n'envoie que le flux.
export default function CameraPanel({ camera, detections }) {
  const [webcam, setWebcam] = useState(false);
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

  return (
    <Panel
      title="Caméra"
      extra={
        <Space>
          {!webcam && <StatusTag tone={persons ? 'danger' : 'ok'}>{persons ? `${persons} personne détectée` : 'RAS'}</StatusTag>}
          <Switch checked={webcam} onChange={toggle} checkedChildren="Webcam PC" unCheckedChildren="Webcam PC" />
        </Space>
      }
    >
      <div className="feed-wrap">
        {webcam ? (
          <WebcamFeed onError={onWebcamError} />
        ) : camera.streamUrl ? (
          <img className="feed" src={camera.streamUrl} alt="Flux caméra" />
        ) : (
          <MockFeed detections={detections} />
        )}
        <span className="feed-tag">
          {webcam ? 'WEBCAM PC' : `CAM-01 · ${camera.width}×${camera.height} · ${camera.fps} fps${camera.streamUrl ? '' : ' · MOCK'}`}
        </span>
      </div>
      {error && <Alert type="error" showIcon title={error} />}
    </Panel>
  );
}
