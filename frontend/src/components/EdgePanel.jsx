import React from 'react';
import { Flex, Typography } from 'antd';
import { Panel, StatusTag, LineChart, Stat } from './ui.jsx';

// Edge Node ESP8266 : gaz (MQ-2, lecture brute 0–1023), présence (PIR) et liaison MQTTS (TLS + certificat client).
// Indépendant du Raspberry : message `edge` sur /ws à chaque mesure de l'ESP (toutes les 2 s) ou changement du PIR.
const STALE_MS = 10_000;

export default function EdgePanel({ edge, gasHistory }) {
  const node = edge.nodes[0]; // un seul boîtier prévu pour la démo
  const alive = node?.online && Date.now() - node.lastSeenMs < STALE_MS;
  const gasHigh = typeof node?.gasRaw === 'number' && node.gasRaw >= edge.gasThreshold;

  const tag = !edge.connected
    ? <StatusTag tone="danger">Broker injoignable</StatusTag>
    : !node
      ? <StatusTag tone="warn">En attente de l'ESP</StatusTag>
      : !alive
        ? <StatusTag tone="danger">Hors ligne</StatusTag>
        : <StatusTag tone="ok">{edge.source === 'mqtt' ? 'En ligne · MQTTS' : 'Simulé'}</StatusTag>;

  return (
    <Panel title="Edge Node (ESP8266)" extra={tag}>
      <Flex gap={24} wrap>
        <Stat title="Gaz (MQ-2)" value={node?.gasRaw ?? '—'} suffix={node?.gasRaw != null && '/ 1023'} />
        <Stat title="Présence (PIR)" value={node?.pir == null ? '—' : node.pir ? 'Oui' : 'Non'} />
        <Stat title="Wi-Fi" value={node?.rssi ?? '—'} suffix={node?.rssi != null && 'dBm'} />
      </Flex>
      {(gasHigh || (alive && node.pir === 1)) && (
        <Flex gap={8} wrap>
          {gasHigh && <StatusTag tone="danger">Gaz au-delà du seuil ({edge.gasThreshold})</StatusTag>}
          {alive && node.pir === 1 && <StatusTag tone="warn">Présence détectée</StatusTag>}
        </Flex>
      )}
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>Gaz (0 – 1023, seuil en pointillés)</Typography.Text>
      <LineChart values={gasHistory} min={0} max={1023} threshold={edge.gasThreshold} color="var(--c-gas)" height={60} />
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        {edge.error
          ? edge.error
          : node
            ? `${node.node} · fw ${node.fw ?? '?'} · ${node.ip ?? '?'} · message n° ${node.seq ?? '—'} · ${node.lost} perdu(s)`
            : edge.broker ? `broker ${edge.broker}` : 'ESP simulé'}
      </Typography.Text>
    </Panel>
  );
}
