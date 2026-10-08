import React, { useState } from 'react';
import { Alert, Button, Flex, Space, Typography } from 'antd';
import { AimOutlined, LeftOutlined, RightOutlined, StopOutlined, SyncOutlined } from '@ant-design/icons';
import { Panel, StatusTag, Stat, SyncedSlider } from './ui.jsx';

function Dial({ angle, target }) {
  const needle = (a, len) => {
    const r = ((a - 90) * Math.PI) / 180;
    return [100 + len * Math.cos(r), 100 + len * Math.sin(r)];
  };
  const [nx, ny] = needle(angle, 70);
  const [tx, ty] = needle(target, 82);
  return (
    <svg viewBox="0 0 200 120" className="dial" role="img" aria-label={`Angle moteur ${angle}°`}>
      <path d="M20,100 A80,80 0 0 1 180,100" className="dial-arc" />
      {[-90, -45, 0, 45, 90].map((a) => {
        const [x1, y1] = needle(a, 80);
        const [x2, y2] = needle(a, 90);
        return <line key={a} x1={x1} y1={y1} x2={x2} y2={y2} className="dial-tick" />;
      })}
      <circle cx={tx} cy={ty} r="4" className="dial-target" />
      <line x1="100" y1="100" x2={nx} y2={ny} className="dial-needle" />
      <circle cx="100" cy="100" r="6" className="dial-hub" />
    </svg>
  );
}

// readOnly : compte « agent » (consultation seule) — l'état du moteur reste visible, les commandes sont désactivées.
export default function MotorPanel({ motor, sendMotor, readOnly = false }) {
  const [error, setError] = useState(null);
  const run = (cmd) => sendMotor(cmd).then(() => setError(null)).catch((e) => setError(e.message));
  const sweeping = motor.mode === 'sweep';

  return (
    <Panel
      title="Moteur (socle)"
      extra={
        <Space size={4}>
          {readOnly && <StatusTag tone="neutral">Lecture seule</StatusTag>}
          <StatusTag tone={sweeping ? 'info' : motor.moving ? 'warn' : 'neutral'}>{sweeping ? 'Balayage' : motor.moving ? 'En mouvement' : 'Arrêté'}</StatusTag>
        </Space>
      }
    >
      <Dial angle={motor.angle} target={motor.target} />
      <Flex gap={24} wrap>
        <Stat title="Angle" value={motor.angle} suffix="°" />
        <Stat title="Cible" value={Math.round(motor.target)} suffix="°" />
        <Stat title="Vitesse" value={motor.speed} suffix="°/s" />
      </Flex>

      <div>
        <Typography.Text type="secondary">Position</Typography.Text>
        <SyncedSlider
          min={-90} max={90} value={motor.target} disabled={sweeping || readOnly}
          marks={{ '-90': '-90°', 0: '0°', 90: '90°' }}
          tooltip={{ formatter: (v) => `${v}°` }}
          onCommit={(angle) => run({ type: 'move', angle })}
        />
      </div>
      <div>
        <Typography.Text type="secondary">Vitesse</Typography.Text>
        <SyncedSlider
          min={5} max={90} step={5} value={motor.speed} disabled={readOnly}
          tooltip={{ formatter: (v) => `${v}°/s` }}
          onCommit={(value) => run({ type: 'speed', value })}
        />
      </div>

      <Space.Compact block>
        <Button block icon={<LeftOutlined />} disabled={sweeping || readOnly} onClick={() => run({ type: 'step', delta: -10 })}>−10°</Button>
        <Button block icon={<AimOutlined />} disabled={sweeping || readOnly} onClick={() => run({ type: 'move', angle: 0 })}>Centrer</Button>
        <Button block icon={<RightOutlined />} iconPlacement="end" disabled={sweeping || readOnly} onClick={() => run({ type: 'step', delta: 10 })}>+10°</Button>
      </Space.Compact>
      <Flex gap={8}>
        <Button block type={sweeping ? 'primary' : 'default'} icon={<SyncOutlined spin={sweeping} />} disabled={readOnly} onClick={() => run({ type: 'sweep', enabled: !sweeping })}>
          {sweeping ? 'Arrêter le balayage' : 'Balayage auto'}
        </Button>
        <Button danger icon={<StopOutlined />} disabled={readOnly} onClick={() => run({ type: 'stop' })}>Stop</Button>
      </Flex>
      {error && <Alert type="error" showIcon title={error} />}
    </Panel>
  );
}
