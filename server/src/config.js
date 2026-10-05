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
  },
  // Seuils utilisés par le moteur d'alertes (indépendants du provider)
  thresholds: {
    proximityCm: 80,
    heatMaxC: 45,
    personConfidence: 0.6,
    envAnomalyScore: 70, // score d'anomalie DHT22 (0..100) au-delà duquel on alerte
  },
};
