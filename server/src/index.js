import http from 'node:http';
import express from 'express';
import { WebSocketServer, WebSocket } from 'ws';
import { config } from './config.js';
import { createProvider } from './providers/index.js';
import { createAnalyzer } from './ai/index.js';
import { createAlertEngine } from './alerts.js';

const provider = createProvider(config);
const analyzer = createAnalyzer(config);
const alertEngine = createAlertEngine({ thresholds: config.thresholds, size: config.alertsSize });

const sensorHistory = []; // points compacts pour les graphiques capteurs
const threatHistory = []; // { ts (du snapshot analysé), score }
let latest = null; // dernier snapshot brut du Raspberry
let analysis = null; // dernier résultat du modèle IA (arrive en différé)
let analyzing = false;

const push = (arr, item) => {
  arr.push(item);
  if (arr.length > config.historySize) arr.shift();
};

const app = express();
app.use(express.json());

const server = http.createServer(app);
const wss = new WebSocketServer({ server, path: '/ws' });

function broadcast(message) {
  const payload = JSON.stringify(message);
  for (const client of wss.clients) {
    if (client.readyState === WebSocket.OPEN) client.send(payload);
  }
}

const broadcastAlerts = (created) => created.forEach((alert) => broadcast({ type: 'alert', data: alert }));

// ---- Chemin rapide : donnée brute du Pi -> front, sans attendre le modèle ----
function onSnapshot(raw) {
  latest = raw;
  push(sensorHistory, { ts: raw.ts, distanceCm: raw.ultrasonic.distanceCm, avgC: raw.thermal.avgC, maxC: raw.thermal.maxC });
  broadcast({ type: 'snapshot', data: raw });
  broadcastAlerts(alertEngine.evaluateSensors(raw));
  runAnalysis(raw); // volontairement non attendu
}

// ---- Chemin lent : modèle IA local, résultat envoyé au front en différé ----
// Pas de file d'attente : si le modèle est occupé, on saute ce snapshot (le suivant sera analysé).
async function runAnalysis(raw) {
  if (analyzing) return;
  analyzing = true;
  const startedAt = Date.now();
  const wasOk = analysis?.ok ?? true;
  try {
    const out = await analyzer.analyze(raw);
    analysis = {
      ok: true,
      source: analyzer.name,
      forTs: raw.ts, // snapshot analysé (pour corréler avec les données brutes)
      ts: Date.now(),
      latencyMs: Date.now() - startedAt,
      detections: out.detections,
      threat: out.threat,
    };
    push(threatHistory, { ts: raw.ts, score: out.threat.score });
    broadcast({ type: 'analysis', data: analysis });
    broadcastAlerts(alertEngine.evaluateAnalysis(analysis));
    if (!wasOk) console.log('[sentinel-x] modèle IA de nouveau disponible');
  } catch (err) {
    analysis = { ok: false, source: analyzer.name, forTs: raw.ts, ts: Date.now(), error: err.message, detections: [], threat: null };
    broadcast({ type: 'analysis', data: analysis });
    if (wasOk) console.warn(`[sentinel-x] modèle IA indisponible : ${err.message}`);
  } finally {
    analyzing = false;
  }
}

// ---- API REST ----
app.get('/api/health', (_req, res) => {
  res.json({ ok: true, provider: provider.name, analyzer: analyzer.name, tickMs: config.tickMs });
});

app.get('/api/snapshot', (_req, res) => {
  latest ? res.json(latest) : res.status(503).json({ error: 'Pas encore de données' });
});

app.get('/api/analysis', (_req, res) => {
  analysis ? res.json(analysis) : res.status(503).json({ error: "Pas encore d'analyse" });
});

app.get('/api/history', (_req, res) => res.json({ sensors: sensorHistory, threat: threatHistory }));
app.get('/api/alerts', (_req, res) => res.json(alertEngine.list()));

app.post('/api/motor', async (req, res) => {
  try {
    const motor = await provider.sendMotorCommand(req.body);
    broadcast({ type: 'motor', data: motor });
    res.json(motor);
  } catch (err) {
    res.status(400).json({ error: err.message });
  }
});

// Scénarios de démo (mock uniquement) : intruder | heat
app.post('/api/mock/:scenario', (req, res) => {
  if (typeof provider.triggerScenario !== 'function') {
    return res.status(404).json({ error: 'Disponible uniquement avec PROVIDER=mock' });
  }
  try {
    provider.triggerScenario(req.params.scenario);
    res.json({ ok: true });
  } catch (err) {
    res.status(400).json({ error: err.message });
  }
});

// ---- WebSocket ----
wss.on('connection', (ws) => {
  ws.send(
    JSON.stringify({
      type: 'hello',
      data: {
        provider: provider.name,
        snapshot: latest,
        analysis,
        history: { sensors: sensorHistory, threat: threatHistory },
        alerts: alertEngine.list(),
      },
    }),
  );
});

provider.start(onSnapshot);

server.listen(config.port, () => {
  console.log(
    `[sentinel-x] API http://localhost:${config.port}  (provider: ${provider.name}, IA: ${analyzer.name}, tick ${config.tickMs} ms)`,
  );
});

for (const sig of ['SIGINT', 'SIGTERM']) {
  process.on(sig, () => {
    provider.stop();
    server.close(() => process.exit(0));
  });
}
