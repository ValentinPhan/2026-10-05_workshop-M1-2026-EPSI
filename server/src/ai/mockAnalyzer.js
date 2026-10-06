// Analyseur factice : remplace le modèle IA tant qu'il n'existe pas.
// Il ne reçoit que des données BRUTES (comme le vrai modèle) : matrice thermique + ultrason + DHT22.
// Une "personne" = tache chaude sur la matrice ET obstacle plus proche que le mur.
// Le DHT22 donne la vraie température ambiante et alimente la détection d'anomalies d'environnement.
import { clamp } from '../providers/motor.js';
import { createEnvDetector } from './envAnomaly.js';

const GRID = 8;
const EMPTY_DISTANCE_CM = 300; // distance mesurée quand la pièce est vide

const median = (arr) => [...arr].sort((a, b) => a - b)[Math.floor(arr.length / 2)];

function detectPerson({ thermal, ultrasonic, environment }) {
  if (!thermal) return []; // sans matrice thermique, l'heuristique ne détecte rien (la caméra est analysée par le vrai modèle)
  // Ambiante : mesure du DHT22 si disponible (fiable même si une personne remplit le champ),
  // sinon médiane de la matrice. +1 °C : la matrice lit un peu plus chaud que l'air (murs, objets).
  const ambient = typeof environment?.tempC === 'number' ? environment.tempC + 1 : median(thermal.grid.flat());
  const body = thermal.maxC - ambient;
  if (body < 4 || ultrasonic.distanceCm > EMPTY_DISTANCE_CM - 30) return [];

  // centre de la tache chaude -> position horizontale dans l'image
  let sum = 0;
  let sumCol = 0;
  thermal.grid.forEach((row) =>
    row.forEach((v, c) => {
      const w = Math.max(0, v - ambient - 1);
      sum += w;
      sumCol += w * c;
    }),
  );
  const x = sum ? sumCol / sum / (GRID - 1) : 0.5;

  const prox = clamp((EMPTY_DISTANCE_CM - ultrasonic.distanceCm) / 250, 0, 1);
  const h = 0.35 + 0.5 * prox;
  const w = h * 0.45;
  return [
    {
      label: 'person',
      confidence: Number(clamp(0.5 + body / 25, 0, 0.99).toFixed(2)),
      bbox: { x: clamp(x - w / 2, 0, 1 - w), y: clamp(0.95 - h, 0, 1 - h), w, h },
    },
  ];
}

// Fusion de capteurs : présence 45 %, proximité 25 %, chaleur 15 %, environnement (DHT22) 15 %.
function threatScore(s, detections, env) {
  const person = Math.max(0, ...detections.filter((d) => d.label === 'person').map((d) => d.confidence));
  const prox = clamp((200 - s.ultrasonic.distanceCm) / 150, 0, 1);
  const heat = s.thermal ? clamp((s.thermal.maxC - 30) / 25, 0, 1) : 0;
  const envRisk = env ? env.score / 100 : 0;
  const score = Math.round(100 * (0.45 * person + 0.25 * prox + 0.15 * heat + 0.15 * envRisk));
  const label = score < 30 ? 'Calme' : score < 60 ? 'Vigilance' : 'Menace';
  return { score, label };
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export function createMockAnalyzer() {
  const envDetector = createEnvDetector();
  return {
    name: 'heuristique (mock)',
    async analyze(snapshot) {
      await sleep(150 + Math.random() * 250); // simule le temps de calcul d'un vrai modèle
      const detections = detectPerson(snapshot);
      const environment = envDetector.update(snapshot.environment);
      return { detections, threat: threatScore(snapshot, detections, environment), environment };
    },
  };
}
