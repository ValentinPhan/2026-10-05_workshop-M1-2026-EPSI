import { useCallback, useEffect, useRef, useState } from 'react';
import { AUTH_EXPIRED, postJson } from '../api.js';

const HISTORY_MAX = 120;
const ALERTS_MAX = 50;
const append = (arr, item) => [...arr, item].slice(-HISTORY_MAX);

// Point d'historique compact (même forme que _sensor_point dans backend/app/hub.py)
const sensorPoint = (s) => ({
  ts: s.ts,
  distanceCm: s.ultrasonic.distanceCm,
  avgC: s.thermal.avgC,
  maxC: s.thermal.maxC,
  envTempC: s.environment?.tempC ?? null,
  humidityPct: s.environment?.humidityPct ?? null,
});

// Connexion WebSocket (reconnexion auto) + état global du dashboard.
// Deux flux indépendants : `snapshot` (donnée brute, chaque seconde) et
// `analysis` (résultat du modèle IA, qui arrive en différé). La vidéo YOLO passe par un autre
// WebSocket (/ws/video), voir useVideoStream.
export function useSentinel() {
  const [connected, setConnected] = useState(false);
  const [provider, setProvider] = useState(null);
  const [snapshot, setSnapshot] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [vision, setVision] = useState(null); // service caméra + YOLO du backend : { enabled, state, fps, model, error }
  const [history, setHistory] = useState([]); // capteurs
  const [threatHistory, setThreatHistory] = useState([]); // { ts, score }
  const [alerts, setAlerts] = useState([]);
  const retryRef = useRef(0);

  useEffect(() => {
    let ws;
    let timer;
    let closed = false;

    const connect = () => {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws';
      ws = new WebSocket(`${proto}://${location.host}/ws`);

      ws.onopen = () => {
        retryRef.current = 0;
        setConnected(true);
      };

      ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        switch (msg.type) {
          case 'hello':
            setProvider(msg.data.provider);
            setSnapshot(msg.data.snapshot);
            setAnalysis(msg.data.analysis);
            setVision(msg.data.vision);
            setHistory(msg.data.history.sensors);
            setThreatHistory(msg.data.history.threat);
            setAlerts(msg.data.alerts);
            break;
          case 'snapshot': {
            const s = msg.data;
            setSnapshot(s);
            setHistory((h) => append(h, sensorPoint(s)));
            break;
          }
          case 'analysis':
            setAnalysis(msg.data);
            if (msg.data.ok) setThreatHistory((h) => append(h, { ts: msg.data.forTs, score: msg.data.threat.score }));
            break;
          case 'vision':
            setVision(msg.data);
            break;
          case 'alert':
            setAlerts((a) => [msg.data, ...a].slice(0, ALERTS_MAX));
            break;
          case 'motor':
            setSnapshot((s) => (s ? { ...s, motor: msg.data } : s));
            break;
        }
      };

      ws.onclose = (event) => {
        setConnected(false);
        if (closed) return;
        if (event.code === 4401) {
          // session refusée : retour à la page de connexion, inutile de réessayer
          closed = true;
          window.dispatchEvent(new Event(AUTH_EXPIRED));
          return;
        }
        // backoff exponentiel plafonné à 5 s
        const delay = Math.min(5000, 500 * 2 ** retryRef.current++);
        timer = setTimeout(connect, delay);
      };
    };

    connect();
    return () => {
      closed = true;
      clearTimeout(timer);
      ws?.close();
    };
  }, []);

  const sendMotor = useCallback((cmd) => postJson('/api/motor', cmd), []);
  const triggerScenario = useCallback((name) => postJson(`/api/mock/${name}`), []);

  return { connected, provider, snapshot, analysis, vision, history, threatHistory, alerts, sendMotor, triggerScenario };
}
