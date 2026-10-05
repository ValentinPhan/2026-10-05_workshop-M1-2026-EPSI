import { useCallback, useEffect, useRef, useState } from 'react';

const HISTORY_MAX = 120;
const ALERTS_MAX = 50;
const append = (arr, item) => [...arr, item].slice(-HISTORY_MAX);

// Connexion WebSocket (reconnexion auto) + état global du dashboard.
// Deux flux indépendants : `snapshot` (donnée brute, chaque seconde) et
// `analysis` (résultat du modèle IA, qui arrive en différé).
export function useSentinel() {
  const [connected, setConnected] = useState(false);
  const [provider, setProvider] = useState(null);
  const [snapshot, setSnapshot] = useState(null);
  const [analysis, setAnalysis] = useState(null);
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
            setHistory(msg.data.history.sensors);
            setThreatHistory(msg.data.history.threat);
            setAlerts(msg.data.alerts);
            break;
          case 'snapshot': {
            const s = msg.data;
            setSnapshot(s);
            setHistory((h) => append(h, { ts: s.ts, distanceCm: s.ultrasonic.distanceCm, avgC: s.thermal.avgC, maxC: s.thermal.maxC }));
            break;
          }
          case 'analysis':
            setAnalysis(msg.data);
            if (msg.data.ok) setThreatHistory((h) => append(h, { ts: msg.data.forTs, score: msg.data.threat.score }));
            break;
          case 'alert':
            setAlerts((a) => [msg.data, ...a].slice(0, ALERTS_MAX));
            break;
          case 'motor':
            setSnapshot((s) => (s ? { ...s, motor: msg.data } : s));
            break;
        }
      };

      ws.onclose = () => {
        setConnected(false);
        if (closed) return;
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

  const post = useCallback(async (url, body) => {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error ?? res.statusText);
    return res.json();
  }, []);

  const sendMotor = useCallback((cmd) => post('/api/motor', cmd), [post]);
  const triggerScenario = useCallback((name) => post(`/api/mock/${name}`), [post]);

  return { connected, provider, snapshot, analysis, history, threatHistory, alerts, sendMotor, triggerScenario };
}
