import React, { useEffect, useState } from 'react';
import { Alert, Button, Col, Flex, Layout, Row, Spin, Typography } from 'antd';
import { LogoutOutlined, SafetyCertificateOutlined } from '@ant-design/icons';
import { useSentinel } from './hooks/useSentinel.js';
import { StatusTag } from './components/ui.jsx';
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

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Layout.Content style={{ maxWidth: 1400, width: '100%', margin: '0 auto', padding: 16 }}>
        <Flex justify="space-between" align="center" wrap gap={12} style={{ marginBottom: 16 }}>
          <Flex align="center" gap={12}>
            <SafetyCertificateOutlined style={{ fontSize: 30, color: '#4fc3dc' }} />
            <div>
              <Typography.Title level={4} style={{ margin: 0, letterSpacing: '0.18em' }}>SENTINEL-X</Typography.Title>
              <Typography.Text type="secondary">AetherCorp Industrial Solutions</Typography.Text>
            </div>
          </Flex>
          <Flex align="center" gap={8} wrap>
            {provider && <StatusTag tone="info">source : {provider}</StatusTag>}
            <StatusTag tone={connected ? 'ok' : 'danger'}>{connected ? 'Connecté' : 'Déconnecté'}</StatusTag>
            <StatusTag tone={isAdmin ? 'info' : 'neutral'}>{user.username} · {isAdmin ? 'administrateur' : 'agent (lecture seule)'}</StatusTag>
            <Clock />
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
            <Col xs={24} xl={16}><CameraPanel camera={snapshot.camera} detections={detections} vision={vision} canControl={isAdmin} /></Col>
            <Col xs={24} xl={8}>
              <Flex vertical gap={16} style={{ height: '100%' }}>
                <ThreatPanel analysis={analysis} threatHistory={threatHistory} />
                <SystemPanel system={snapshot.system} />
              </Flex>
            </Col>
            <Col xs={24} md={12} xl={8}><UltrasonicPanel ultrasonic={snapshot.ultrasonic} angle={snapshot.motor.angle} history={history} /></Col>
            {snapshot.thermal && <Col xs={24} md={12} xl={8}><ThermalPanel thermal={snapshot.thermal} history={history} /></Col>}
            <Col xs={24} md={12} xl={8}><EnvironmentPanel environment={snapshot.environment} analysis={analysis} history={history} /></Col>
            <Col xs={24} md={12} xl={8}><MotorPanel motor={snapshot.motor} sendMotor={sendMotor} readOnly={!isAdmin} /></Col>
            <Col xs={24} xl={isAdmin ? 8 : 16}>
              <AlertsPanel alerts={alerts} triggerScenario={triggerScenario} mock={provider === 'mock' && isAdmin} />
            </Col>
            {isAdmin && <Col xs={24} xl={8}><UsersPanel currentUser={user} /></Col>}
          </Row>
        )}
      </Layout.Content>
    </Layout>
  );
}
