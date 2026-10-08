import React, { useState } from 'react';
import { Alert, Button, Card, Flex, Form, Input, Layout, Typography } from 'antd';
import { LockOutlined, SafetyCertificateOutlined, UserOutlined } from '@ant-design/icons';

export default function LoginPage({ onLogin }) {
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const submit = async ({ username, password }) => {
    setBusy(true);
    setError(null);
    try {
      await onLogin(username, password);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Flex justify="center" align="center" style={{ flex: 1, padding: 16 }}>
        <Card style={{ width: 360, maxWidth: '100%' }}>
          <Flex vertical align="center" gap={4} style={{ marginBottom: 20 }}>
            <SafetyCertificateOutlined style={{ fontSize: 36, color: '#4fc3dc' }} />
            <Typography.Title level={4} style={{ margin: 0, letterSpacing: '0.18em' }}>SENTINEL-X</Typography.Title>
            <Typography.Text type="secondary">Connexion au tableau de bord</Typography.Text>
          </Flex>
          <Form layout="vertical" onFinish={submit} requiredMark={false}>
            <Form.Item name="username" label="Identifiant" rules={[{ required: true, message: 'Identifiant requis' }]}>
              <Input prefix={<UserOutlined />} autoComplete="username" autoFocus />
            </Form.Item>
            <Form.Item name="password" label="Mot de passe" rules={[{ required: true, message: 'Mot de passe requis' }]}>
              <Input.Password prefix={<LockOutlined />} autoComplete="current-password" />
            </Form.Item>
            {error && <Alert type="error" showIcon title={error} style={{ marginBottom: 16 }} />}
            <Button type="primary" htmlType="submit" block loading={busy}>Se connecter</Button>
          </Form>
        </Card>
      </Flex>
    </Layout>
  );
}
