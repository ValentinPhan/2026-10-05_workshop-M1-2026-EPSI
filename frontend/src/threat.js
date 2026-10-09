// Couleurs d'état utilisées dans les canvas et les jauges (miroir de --ok / --warn / --danger dans styles.css et du
// thème Ant Design dans main.jsx : un canvas ne lit pas les variables CSS).
export const STATUS_COLORS = { ok: '#3ecf8e', warn: '#f5a524', danger: '#ff5a4f' };

// Niveaux de menace renvoyés par le modèle IA (backend/app/ai/threat.py : « Calme » / « Vigilance » / « Menace »).
// Une seule table pour le ton des tags, la couleur des jauges et l'humeur de la mascotte (valeurs de
// `data-mood`, voir styles.css). Un libellé inconnu retombe sur « Calme » côté mascotte.
export const THREAT_LEVELS = {
  Calme: { tone: 'ok', color: STATUS_COLORS.ok, mood: 'calme' },
  Vigilance: { tone: 'warn', color: STATUS_COLORS.warn, mood: 'vigilance' },
  Menace: { tone: 'danger', color: STATUS_COLORS.danger, mood: 'menace' },
};

// Ce que dit la mascotte selon son humeur (`offline` : API injoignable).
export const MOOD_SAYINGS = {
  calme: 'Bello ! Tout est calme.',
  vigilance: 'Hmm… poo-tay-to ? Je surveille.',
  menace: 'Bee-do bee-do ! Intrus !',
  offline: 'Zzz… plus de réseau.',
};
