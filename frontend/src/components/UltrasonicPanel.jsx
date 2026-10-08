import React from 'react';
import { Flex } from 'antd';
import { Panel, StatusTag, LineChart, Stat } from './ui.jsx';

const CX = 150, CY = 150, R = 130;

// Radar : le faisceau suit l'angle du moteur, le point est l'obstacle mesuré.
function Radar({ distanceCm, maxRangeCm, angle }) {
  const rad = ((angle - 90) * Math.PI) / 180;
  const pt = (r) => [CX + r * Math.cos(rad), CY + r * Math.sin(rad)];
  const [bx, by] = pt(R);
  const [px, py] = pt((Math.min(distanceCm, maxRangeCm) / maxRangeCm) * R);
  const near = distanceCm < 80;
  return (
    <svg viewBox="0 0 300 165" className="radar" role="img" aria-label="Radar ultrason">
      {[0.25, 0.5, 0.75, 1].map((k) => (
        <path key={k} d={`M${CX - R * k},${CY} A${R * k},${R * k} 0 0 1 ${CX + R * k},${CY}`} className="radar-ring" />
      ))}
      {[-60, -30, 0, 30, 60].map((a) => {
        const r2 = ((a - 90) * Math.PI) / 180;
        return <line key={a} x1={CX} y1={CY} x2={CX + R * Math.cos(r2)} y2={CY + R * Math.sin(r2)} className="radar-ring" />;
      })}
      <line x1={CX} y1={CY} x2={bx} y2={by} className="radar-beam" />
      <circle cx={px} cy={py} r="6" className={near ? 'radar-blip near' : 'radar-blip'} />
      {[1, 2, 3, 4].map((k) => (
        <text key={k} x={CX + (R * k) / 4} y={CY + 12} className="radar-label">{(maxRangeCm * k) / 4}</text>
      ))}
    </svg>
  );
}

export default function UltrasonicPanel({ ultrasonic, angle, history }) {
  const { distanceCm, maxRangeCm } = ultrasonic;
  const near = distanceCm < 80;
  return (
    <Panel title="Capteur ultrason" extra={<StatusTag tone={near ? 'warn' : 'ok'}>{near ? 'Proche' : 'Dégagé'}</StatusTag>}>
      <Radar distanceCm={distanceCm} maxRangeCm={maxRangeCm} angle={angle} />
      <Flex gap={24} wrap>
        <Stat title="Distance" value={Math.round(distanceCm)} suffix="cm" />
        <Stat title="Portée max" value={maxRangeCm} suffix="cm" />
      </Flex>
      <LineChart values={history.map((h) => h.distanceCm)} min={0} max={maxRangeCm} threshold={80} color="var(--c-ultra)" />
    </Panel>
  );
}
