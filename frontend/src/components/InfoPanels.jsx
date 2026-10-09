import { Button, Flex, Image, List, Progress, Typography } from 'antd';
import { Panel, StatusTag, LineChart, Stat } from './ui.jsx';
import { THREAT_LEVELS } from '../threat.js';

// `analysis` arrive en différé du modèle IA : null (pas encore de résultat),
// { ok: false } (modèle injoignable) ou { ok: true, threat, latencyMs, source }.
export function ThreatPanel({ analysis, threatHistory }) {
  const threat = analysis?.ok ? analysis.threat : null;
  const tag = !analysis
    ? <StatusTag>En attente du modèle</StatusTag>
    : !analysis.ok
      ? <StatusTag tone="danger">IA hors ligne</StatusTag>
      : <StatusTag tone={THREAT_LEVELS[threat.label]?.tone}>{threat.label}</StatusTag>;

  return (
    <Panel title="Score de menace" extra={tag}>
      <Flex vertical align="center" gap={4}>
        <Progress
          type="dashboard"
          percent={threat?.score ?? 0}
          strokeColor={threat ? THREAT_LEVELS[threat.label]?.color : undefined}
          format={() => (threat ? threat.score : '—')}
          size={140}
        />
        <Typography.Text type="secondary">
          {analysis?.ok ? `Modèle : ${analysis.source} · calculé en ${analysis.latencyMs} ms` : analysis ? `Modèle injoignable : ${analysis.error}` : 'Le score arrive en différé des données brutes'}
        </Typography.Text>
      </Flex>
      <LineChart values={threatHistory.map((h) => h.score)} min={0} max={100} color="var(--c-threat)" />
    </Panel>
  );
}

const fmtUptime = (s) => {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h ? `${h} h ${String(m).padStart(2, '0')} min` : `${m} min ${String(s % 60).padStart(2, '0')} s`;
};

const load = (label, percent) => (
  <div>
    <Typography.Text type="secondary">{label}</Typography.Text>
    <Progress percent={percent} size="small" status={percent > 85 ? 'exception' : 'normal'} />
  </div>
);

export function SystemPanel({ system }) {
  return (
    <Panel title="Raspberry Pi" extra={<StatusTag tone="info">{system.link}</StatusTag>}>
      {load('CPU', system.cpuPct)}
      {load('RAM', system.ramPct)}
      <Flex gap={32} wrap>
        <Stat title="Temp. CPU" value={system.cpuTempC} suffix="°C" />
        <Stat title="Uptime" value={fmtUptime(system.uptimeS)} />
      </Flex>
    </Panel>
  );
}

const LEVEL_TONE = { critical: 'danger', warning: 'warn', info: 'info' };

export function AlertsPanel({ alerts, triggerScenario, mock }) {
  return (
    <Panel title="Journal des banana-alertes" extra={<StatusTag>{alerts.length}</StatusTag>}>
      {mock && (
        <Flex gap={8} wrap>
          <Button size="small" onClick={() => triggerScenario('intruder')}>Simuler un intrus</Button>
          <Button size="small" onClick={() => triggerScenario('heat')}>Simuler un pic thermique</Button>
          <Button size="small" onClick={() => triggerScenario('window')}>Simuler une fenêtre ouverte</Button>
        </Flex>
      )}
      <List
        size="small"
        style={{ maxHeight: 260, overflowY: 'auto' }}
        locale={{ emptyText: 'Aucune alerte · les Minions sont calmes' }}
        dataSource={alerts}
        rowKey="id"
        renderItem={(a) => (
          <List.Item>
            <Flex gap={12} align="center">
              <StatusTag tone={LEVEL_TONE[a.level]}>{a.level}</StatusTag>
              <Typography.Text type="secondary">{new Date(a.ts).toLocaleTimeString('fr-FR')}</Typography.Text>
              <span>{a.message}</span>
              {a.snapshot && (
                <Image src={a.snapshot} alt="Photo de l'intrusion" width={56} height={42} style={{ objectFit: 'cover', borderRadius: 4 }} />
              )}
            </Flex>
          </List.Item>
        )}
      />
    </Panel>
  );
}
