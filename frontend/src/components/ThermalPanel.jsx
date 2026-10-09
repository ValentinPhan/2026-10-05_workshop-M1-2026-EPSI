import { Flex } from 'antd';
import { Panel, StatusTag, LineChart, Stat } from './ui.jsx';

// Rampe thermique (sombre -> clair) : 20 °C = froid, 50 °C = très chaud.
const STOPS = [
  [0, [12, 20, 44]],
  [0.35, [34, 86, 150]],
  [0.65, [240, 140, 40]],
  [1, [255, 235, 140]],
];
const T_MIN = 20;
const T_MAX = 50;

function heatColor(v) {
  const k = Math.min(1, Math.max(0, (v - T_MIN) / (T_MAX - T_MIN)));
  for (let i = 1; i < STOPS.length; i++) {
    const [k1, c1] = STOPS[i];
    const [k0, c0] = STOPS[i - 1];
    if (k <= k1) {
      const f = (k - k0) / (k1 - k0);
      return `rgb(${c0.map((c, j) => Math.round(c + (c1[j] - c) * f)).join(',')})`;
    }
  }
  return `rgb(${STOPS.at(-1)[1].join(',')})`;
}

export default function ThermalPanel({ thermal, history }) {
  const hot = thermal.maxC > 45;
  return (
    <Panel title="Capteur thermique" extra={<StatusTag tone={hot ? 'danger' : 'ok'}>{hot ? 'Surchauffe' : 'Normal'}</StatusTag>}>
      <div className="heatmap" role="img" aria-label="Matrice thermique 8x8">
        {thermal.grid.flat().map((v, i) => (
          <div key={i} className="heat-cell" style={{ background: heatColor(v) }} title={`${v} °C`} />
        ))}
      </div>
      <Flex gap={24} wrap>
        <Stat title="Moyenne" value={thermal.avgC} suffix="°C" />
        <Stat title="Maximum" value={thermal.maxC} suffix="°C" />
      </Flex>
      <LineChart values={history.map((h) => h.maxC)} min={20} max={60} threshold={45} color="var(--c-thermal)" />
    </Panel>
  );
}
