// Configuration centrale, surchargeable par variables d'environnement.
const num = (v, d) => (v !== undefined && !Number.isNaN(Number(v)) ? Number(v) : d);

export const config = {
  port: num(process.env.PORT, 4000),
  // "mock" (données fictives) ou "ssh" (Raspberry Pi réel)
  provider: process.env.PROVIDER ?? 'mock',
  // Modèle IA local (score de menace + détections) : "mock" (heuristique) ou "http" (service Python)
  analyzer: process.env.ANALYZER ?? 'mock',
  aiUrl: process.env.AI_URL ?? 'http://localhost:8000',
  aiTimeoutMs: num(process.env.AI_TIMEOUT_MS, 800),
  tickMs: num(process.env.TICK_MS, 1000),
  historySize: num(process.env.HISTORY_SIZE, 120),
  alertsSize: num(process.env.ALERTS_SIZE, 50),
  ssh: {
    host: process.env.SSH_HOST ?? '192.168.50.10',
    port: num(process.env.SSH_PORT, 22),
    username: process.env.SSH_USER ?? 'pi',
    privateKeyPath: process.env.SSH_KEY ?? '',
    password: process.env.SSH_PASSWORD ?? '', // alternative à la clé ; ne jamais le mettre dans le dépôt
    // Commande lancée sur le Pi (le dépôt y est cloné / copié dans ~/sentinel-x)
    command: process.env.AGENT_COMMAND ?? 'python3 ~/sentinel-x/pi/sentinel_agent.py',
    streamUrl: process.env.STREAM_URL ?? '', // flux MJPEG de la caméra du Pi
    local: process.env.AGENT_LOCAL === '1', // lance l'agent --fake sur ce PC (test sans Raspberry)
  },
  // Seuils utilisés par le moteur d'alertes (indépendants du provider)
  thresholds: {
    proximityCm: 80,
    heatMaxC: 45,
    personConfidence: 0.6,
    envAnomalyScore: 70, // score d'anomalie DHT22 (0..100) au-delà duquel on alerte
  },
};
