// Détection d'anomalies sur le DHT22 (température + humidité de la pièce).
//
// Version "en ligne" sans dépendance, utilisée par l'analyseur mock : elle apprend en continu
// la normale de chaque variable (moyenne et variance glissantes, EWMA) et note l'écart de la
// mesure courante (z-score). Le modèle entraîné hors ligne (Isolation Forest, ai/env_model.py)
// utilise les mêmes variables dérivées et le même format de sortie.
//
// Sortie : { score: 0..100, label: 'Normal'|'Inhabituel'|'Anomalie', dewPointC, reasons: [string] }

const WINDOW_MS = 15 * 60_000; // historique conservé pour les pentes
const SLOPE_MS = 60_000; // pente calculée sur 1 min
const WARMUP = 30; // nb de mesures avant de noter (le temps d'apprendre la normale)
const ALPHA = 0.02; // vitesse d'apprentissage de la normale

// Variables suivies ; `floor` = écart-type minimal (évite les z-scores énormes sur un signal très stable)
const FEATURES = {
  tempC: { floor: 0.4, text: (d) => `température ${d > 0 ? 'anormalement haute' : 'anormalement basse'}` },
  humidityPct: { floor: 2, text: (d) => `humidité ${d > 0 ? 'anormalement haute' : 'anormalement basse'}` },
  dTempPerMin: { floor: 0.15, text: (d) => (d > 0 ? 'température qui monte vite' : 'température qui chute vite') },
  dHumPerMin: { floor: 0.6, text: (d) => (d > 0 ? 'humidité qui monte vite' : 'humidité qui chute vite') },
};

// Point de rosée (formule de Magnus) : en dessous, l'air condense.
export function dewPoint(tempC, humidityPct, a = 17.62, b = 243.12) {
  const g = Math.log(Math.max(humidityPct, 1) / 100) + (a * tempC) / (b + tempC);
  return (b * g) / (a - g);
}

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

export function createEnvDetector() {
  const readings = []; // { ts, tempC, humidityPct } — une entrée par mesure DHT22 réelle
  const stats = Object.fromEntries(Object.keys(FEATURES).map((k) => [k, { mean: 0, var: 0 }]));
  let count = 0;
  let last = null;

  // Pente (unité / min) entre la mesure courante et celle d'il y a ~1 min
  function slope(key, now) {
    const ref = readings.find((r) => now.ts - r.ts <= SLOPE_MS) ?? readings[0];
    if (!ref) return 0;
    const dtMin = (now.ts - ref.ts) / 60_000;
    return dtMin > 0.1 ? (now[key] - ref[key]) / dtMin : 0;
  }

  function evaluate(env) {
    const dewPointC = Number(dewPoint(env.tempC, env.humidityPct).toFixed(1));
    const now = { ts: env.readAt, tempC: env.tempC, humidityPct: env.humidityPct };
    const x = {
      tempC: now.tempC,
      humidityPct: now.humidityPct,
      dTempPerMin: slope('tempC', now),
      dHumPerMin: slope('humidityPct', now),
    };

    // 1) Score statistique : plus grand écart à la normale apprise
    let maxZ = 0;
    const reasons = [];
    if (count >= WARMUP) {
      for (const [k, f] of Object.entries(FEATURES)) {
        const sd = Math.max(Math.sqrt(stats[k].var), f.floor);
        const z = (x[k] - stats[k].mean) / sd;
        if (Math.abs(z) > 3) reasons.push(f.text(z));
        maxZ = Math.max(maxZ, Math.abs(z));
      }
    }
    let score = Math.round(clamp(((maxZ - 2.5) / 4) * 100, 0, 100));

    // 2) Garde-fous déterministes (marchent même pendant l'apprentissage)
    if (env.tempC > 45 || x.dTempPerMin > 2) {
      score = 100;
      reasons.unshift('montée de température critique (risque incendie / surchauffe)');
    }
    if (env.tempC - dewPointC < 1.5) {
      score = Math.max(score, 70);
      reasons.push('air proche de la saturation (risque de condensation)');
    }

    // 3) Apprentissage : la normale n'apprend pas des anomalies, sinon elle finirait par les accepter
    if (count < WARMUP || score < 40) {
      for (const k of Object.keys(FEATURES)) {
        const s = stats[k];
        if (count === 0) {
          s.mean = x[k];
          continue;
        }
        const a = count < WARMUP ? 1 / (count + 1) : ALPHA; // moyenne simple pendant l'apprentissage
        const d = x[k] - s.mean;
        s.mean += a * d;
        s.var = (1 - a) * (s.var + a * d * d);
      }
      count++;
    }

    const label = count < WARMUP ? 'Apprentissage' : score < 40 ? 'Normal' : score < 70 ? 'Inhabituel' : 'Anomalie';
    return { score, label, dewPointC, reasons, learning: count < WARMUP };
  }

  return {
    // `env` = snapshot.environment du Pi. Ne recalcule que si une nouvelle mesure DHT22 est arrivée.
    update(env) {
      if (!env || typeof env.tempC !== 'number' || typeof env.humidityPct !== 'number') return null;
      if (last && env.readAt === last.readAt) return last.result;
      // lecture aberrante (glitch du protocole) : saut de plus de 5 °C entre deux mesures proches
      const prev = readings.at(-1);
      const glitch = prev && env.readAt - prev.ts < 10_000 && Math.abs(env.tempC - prev.tempC) > 5;
      if (env.humidityPct < 0 || env.humidityPct > 100 || glitch) {
        return last?.result ?? null;
      }
      const result = evaluate(env);
      readings.push({ ts: env.readAt, tempC: env.tempC, humidityPct: env.humidityPct });
      while (readings.length && env.readAt - readings[0].ts > WINDOW_MS) readings.shift();
      last = { readAt: env.readAt, result };
      return result;
    },
  };
}
