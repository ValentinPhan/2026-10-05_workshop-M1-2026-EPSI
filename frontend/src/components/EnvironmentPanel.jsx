import { Flex, Progress, Typography } from 'antd';
import { Panel, StatusTag, LineChart, Stat } from './ui.jsx';
import { STATUS_COLORS } from '../threat.js';

// Capteur DHT22 : mesures brutes immédiates (température, humidité) + analyse du modèle IA en différé
// (point de rosée, score d'anomalie, raisons).
const STALE_MS = 10_000; // le DHT22 mesure toutes les 2 s : au-delà de 10 s sans lecture, il est muet
const TONES = { Apprentissage: 'info', Normal: 'ok', Inhabituel: 'warn', Anomalie: 'danger' };
const COLORS = { Normal: STATUS_COLORS.ok, Inhabituel: STATUS_COLORS.warn, Anomalie: STATUS_COLORS.danger };

const series = (history, key) => history.map((h) => h[key]).filter((v) => typeof v === 'number');

export default function EnvironmentPanel({ environment, analysis, history }) {
  const hasReading = typeof environment?.tempC === 'number';
  const stale = !hasReading || Date.now() - environment.readAt > STALE_MS;
  const env = analysis?.ok ? analysis.environment : null;

  const tag = !hasReading
    ? <StatusTag tone="danger">Pas de mesure</StatusTag>
    : stale
      ? <StatusTag tone="warn">Capteur muet</StatusTag>
      : env
        ? <StatusTag tone={TONES[env.label]}>{env.label}</StatusTag>
        : <StatusTag>En attente du modèle</StatusTag>;

  return (
    <Panel title="Environnement (DHT22)" extra={tag}>
      <Flex gap={24} wrap>
        <Stat title="Température" value={hasReading ? environment.tempC : '—'} suffix={hasReading && '°C'} />
        <Stat title="Humidité" value={hasReading ? environment.humidityPct : '—'} suffix={hasReading && '%'} />
        <Stat title="Point de rosée" value={env ? env.dewPointC : '—'} suffix={env && '°C'} />
      </Flex>
      <div>
        <Typography.Text type="secondary">Score d'anomalie (IA)</Typography.Text>
        <Progress
          percent={env?.score ?? 0}
          size="small"
          strokeColor={env ? COLORS[env.label] : undefined}
          format={() => (env && !env.learning ? env.score : '—')}
        />
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {!env
            ? 'Le score arrive en différé des mesures'
            : env.learning
              ? 'Le modèle apprend la normale de la pièce…'
              : env.reasons.length
                ? env.reasons.join(' · ')
                : 'Conforme à la normale apprise'}
        </Typography.Text>
      </div>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>Température (10 – 40 °C)</Typography.Text>
      <LineChart values={series(history, 'envTempC')} min={10} max={40} color="var(--c-env-temp)" height={50} />
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>Humidité (0 – 100 %)</Typography.Text>
      <LineChart values={series(history, 'humidityPct')} min={0} max={100} color="var(--c-env-hum)" height={50} />
    </Panel>
  );
}
