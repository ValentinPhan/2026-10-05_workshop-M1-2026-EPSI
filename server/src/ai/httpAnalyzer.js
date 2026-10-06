// Client du modèle IA local (service Python : YOLO + détection d'anomalies, sur ce PC).
//
// Contrat :  POST {AI_URL}/analyze
//   corps    : le snapshot brut du Raspberry (JSON, voir providers/sshProvider.js)
//   réponse  : { detections: [{label, confidence, bbox:{x,y,w,h}}],   // bbox normalisée 0..1
//                threat: { score: 0..100, label: 'Calme'|'Vigilance'|'Menace' },
//                environment?: { score: 0..100, label, dewPointC, reasons: [string] } }   // DHT22, optionnel
//   (`environment` : voir ai/env_model.py, Isolation Forest sur température / humidité)
//
// L'image n'est pas dans le snapshot (trop lourde) : le service lit lui-même le flux
// de la caméra via `camera.streamUrl`.
export function createHttpAnalyzer({ url, timeoutMs }) {
  return {
    name: 'modèle IA local',
    async analyze(snapshot) {
      const res = await fetch(`${url}/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(snapshot),
        signal: AbortSignal.timeout(timeoutMs),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const out = await res.json();
      if (!Array.isArray(out.detections) || typeof out.threat?.score !== 'number') {
        throw new Error('réponse du modèle invalide');
      }
      return { ...out, environment: out.environment ?? null };
    },
  };
}
