// Moteur d'alertes, indépendant du provider et du modèle IA.
// Deux chemins :
//   - evaluateSensors(snapshot) : seuils sur la donnée brute (immédiat, marche sans IA)
//   - evaluateAnalysis(analysis) : règles qui dépendent du modèle IA (intrusion, anomalie d'environnement)
// Une alerte est émise au passage "condition fausse -> vraie" (pas à chaque tick).
export function createAlertEngine({ thresholds, size }) {
  const alerts = [];
  const active = new Set();
  let nextId = 1;

  function run(rules, ts) {
    const created = [];
    for (const rule of rules) {
      if (rule.on && !active.has(rule.key)) {
        active.add(rule.key);
        const alert = { id: nextId++, ts, level: rule.level, key: rule.key, message: rule.message };
        alerts.unshift(alert);
        created.push(alert);
      } else if (!rule.on) {
        active.delete(rule.key);
      }
    }
    alerts.length = Math.min(alerts.length, size);
    return created;
  }

  return {
    evaluateSensors(s) {
      return run(
        [
          {
            key: 'proximity',
            level: 'warning',
            on: s.ultrasonic.distanceCm < thresholds.proximityCm,
            message: `Objet à ${Math.round(s.ultrasonic.distanceCm)} cm du capteur ultrason`,
          },
          {
            key: 'heat',
            level: 'warning',
            on: Boolean(s.thermal) && s.thermal.maxC > thresholds.heatMaxC, // pas de matrice thermique : pas d'alerte
            message: `Pic thermique : ${s.thermal?.maxC} °C (seuil ${thresholds.heatMaxC} °C)`,
          },
        ],
        s.ts,
      );
    },

    // Modèle indisponible (ok: false) : on ne touche pas aux alertes IA, rien n'est analysé.
    evaluateAnalysis(a) {
      if (!a.ok) return [];
      const person = a.detections.find((d) => d.label === 'person' && d.confidence >= thresholds.personConfidence);
      const env = a.environment;
      return run(
        [
          {
            key: 'intrusion',
            level: 'critical',
            on: Boolean(person),
            message: person ? `Intrusion détectée par le modèle IA (personne, ${Math.round(person.confidence * 100)} %)` : '',
          },
          {
            key: 'environment',
            level: 'warning',
            on: Boolean(env && env.score >= thresholds.envAnomalyScore),
            message: env ? `Anomalie d'environnement (DHT22, score ${env.score}) : ${env.reasons.join(', ') || 'écart à la normale'}` : '',
          },
        ],
        a.ts,
      );
    },

    list: () => alerts,
  };
}
