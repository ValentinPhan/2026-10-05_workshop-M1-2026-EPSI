import { useEffect, useState } from 'react';
import { Alert, Button, Col, Flex, Row, Spin, Tooltip, Typography } from 'antd';
import { LogoutOutlined, MutedOutlined, SoundOutlined } from '@ant-design/icons';
import { useSentinel } from './hooks/useSentinel.js';
import { useAlarm } from './hooks/useAlarm.js';
import { MOOD_SAYINGS, THREAT_LEVELS } from './threat.js';
import { StatusTag } from './components/ui.jsx';
import Minion from './components/Minion.jsx';
import CameraPanel from './components/CameraPanel.jsx';
import UltrasonicPanel from './components/UltrasonicPanel.jsx';
import ThermalPanel from './components/ThermalPanel.jsx';
import MotorPanel from './components/MotorPanel.jsx';
import EnvironmentPanel from './components/EnvironmentPanel.jsx';
import UsersPanel from './components/UsersPanel.jsx';
import { ThreatPanel, SystemPanel, AlertsPanel } from './components/InfoPanels.jsx';

const DETECTIONS_MAX_AGE_MS = 3000;

function Clock() {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  return <Typography.Text type="secondary">{now.toLocaleTimeString('fr-FR')}</Typography.Text>;
}

// `user.role` : « admin » peut tout (moteur / caméra, source vidéo, simulations, comptes) ;
// « agent » est en consultation seule. Le backend applique les mêmes règles : l'interface ne fait que les refléter.
export default function Dashboard({ user, onLogout }) {
  const { connected, provider, snapshot, analysis, vision, history, threatHistory, alerts, sendMotor, triggerScenario } = useSentinel();
  const isAdmin = user.role === 'admin';

  // Les détections arrivent en différé : au-delà de 3 s elles ne correspondent plus à l'image.
  const detections = analysis?.ok && Date.now() - analysis.ts < DETECTIONS_MAX_AGE_MS ? analysis.detections : [];

  // humeur de la mascotte (et de l'ambiance de l'écran) d'après la menace et la connexion à l'API
  const mood = !connected ? 'offline' : THREAT_LEVELS[analysis?.ok && analysis.threat.label]?.mood ?? 'calme';
  const alarm = useAlarm(mood === 'menace'); // sirène « bee-do » pendant une menace, coupable avec le bouton de l'en-tête
  // chaque Col entre en cascade (--i = rang d'apparition)
  const rise = (i) => ({ className: 'rise', style: { '--i': i } });

  return (
    <div className="app-shell" data-mood={mood}>
      <div style={{ maxWidth: 1400, width: '100%', margin: '0 auto', padding: 16 }}>
        <Flex justify="space-between" align="flex-end" wrap gap={12} style={{ marginBottom: 20 }}>
          <Flex align="flex-end" gap={14}>
            <Minion mood={mood} height={120} className="minion-head" />
            <Flex vertical gap={6} style={{ paddingBottom: 8 }}>
              <div>
                <h1 className="wordmark">SENTINEL<b>-X</b></h1>
                <span className="tagline">AetherCorp Industrial Solutions</span>
              </div>
              <span key={mood} className="say">{MOOD_SAYINGS[mood]}</span>
            </Flex>
          </Flex>
          <Flex align="center" gap={8} wrap>
            {provider && <StatusTag tone="info">source : {provider}</StatusTag>}
            <StatusTag tone={connected ? 'ok' : 'danger'}>{connected ? 'Connecté' : 'Déconnecté'}</StatusTag>
            <StatusTag tone={isAdmin ? 'info' : 'neutral'}>{user.username} · {isAdmin ? 'administrateur' : 'agent (lecture seule)'}</StatusTag>
            <Clock />
            <Tooltip title={alarm.enabled ? 'Couper la sirène sonore' : 'Activer la sirène sonore'}>
              <Button size="small" icon={alarm.enabled ? <SoundOutlined /> : <MutedOutlined />} onClick={alarm.toggle} aria-label="Sirène sonore" aria-pressed={alarm.enabled} />
            </Tooltip>
            <Button size="small" icon={<LogoutOutlined />} onClick={onLogout}>Déconnexion</Button>
          </Flex>
        </Flex>

        {!connected && snapshot && (
          <Alert type="warning" showIcon title="Connexion à l'API perdue, reconnexion en cours… les données affichées sont figées." style={{ marginBottom: 16 }} />
        )}

        {!snapshot ? (
          <Flex justify="center" style={{ padding: 60 }}>
            <Spin size="large" description={connected ? 'En attente des premières données…' : 'Connexion à l’API…'}>
              <div style={{ padding: 50 }} />
            </Spin>
          </Flex>
        ) : (
          <Row gutter={[16, 16]}>
            <Col xs={24} xl={16} {...rise(0)}><CameraPanel camera={snapshot.camera} detections={detections} vision={vision} canControl={isAdmin} /></Col>
            <Col xs={24} xl={8} {...rise(1)}>
              <Flex vertical gap={16} style={{ height: '100%' }}>
                <ThreatPanel analysis={analysis} threatHistory={threatHistory} />
                <SystemPanel system={snapshot.system} />
              </Flex>
            </Col>
            <Col xs={24} md={12} xl={8} {...rise(2)}><UltrasonicPanel ultrasonic={snapshot.ultrasonic} angle={snapshot.motor.angle} history={history} /></Col>
            <Col xs={24} md={12} xl={8} {...rise(3)}><ThermalPanel thermal={snapshot.thermal} history={history} /></Col>
            <Col xs={24} md={12} xl={8} {...rise(4)}><EnvironmentPanel environment={snapshot.environment} analysis={analysis} history={history} /></Col>
            <Col xs={24} md={12} xl={8} {...rise(5)}><MotorPanel motor={snapshot.motor} sendMotor={sendMotor} readOnly={!isAdmin} /></Col>
            <Col xs={24} xl={isAdmin ? 8 : 16} {...rise(6)}>
              <AlertsPanel alerts={alerts} triggerScenario={triggerScenario} mock={provider === 'mock' && isAdmin} />
            </Col>
            {isAdmin && <Col xs={24} xl={8} {...rise(7)}><UsersPanel currentUser={user} /></Col>}
          </Row>
        )}
      </div>
    </div>
  );
}
