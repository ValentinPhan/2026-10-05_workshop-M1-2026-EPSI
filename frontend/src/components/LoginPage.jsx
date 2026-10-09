import { useState } from 'react';
import { Alert, Button, Card, Form, Input } from 'antd';
import { LockOutlined, UserOutlined } from '@ant-design/icons';
import Minion from './Minion.jsx';

// La mascotte réagit : elle se couvre les yeux pendant la saisie du mot de passe, se méfie pendant la vérification
// et se fâche (la carte tremble) si l'identifiant ou le mot de passe est refusé.
export default function LoginPage({ onLogin }) {
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [shy, setShy] = useState(false);
  const [shaking, setShaking] = useState(false);

  const submit = async ({ username, password }) => {
    setBusy(true);
    setError(null);
    try {
      await onLogin(username, password);
    } catch (e) {
      setError(e.message);
      setShaking(true);
    } finally {
      setBusy(false);
    }
  };

  const mood = error ? 'menace' : busy ? 'vigilance' : 'calme';

  return (
    <div className="app-shell login-wrap" data-mood={error ? 'menace' : null}>
      <div className="login-stack">
        <Minion mood={mood} shy={shy && !error} height={230} />
        <h1 className="login-title">Bello<b> !</b></h1>
        <span className="tagline">SENTINEL-X · identifiez-vous pour entrer dans le labo</span>
        <Card className={`login-card${shaking ? ' shake' : ''}`} onAnimationEnd={() => setShaking(false)}>
          <Form layout="vertical" onFinish={submit} requiredMark={false}>
            <Form.Item name="username" label="Identifiant" rules={[{ required: true, message: 'Identifiant requis' }]}>
              <Input prefix={<UserOutlined />} autoComplete="username" autoFocus />
            </Form.Item>
            <Form.Item name="password" label="Mot de passe" rules={[{ required: true, message: 'Mot de passe requis' }]}>
              <Input.Password
                prefix={<LockOutlined />}
                autoComplete="current-password"
                onFocus={() => setShy(true)}
                onBlur={() => setShy(false)}
              />
            </Form.Item>
            {error && <Alert type="error" showIcon title={error} style={{ marginBottom: 16 }} />}
            <Button type="primary" htmlType="submit" block loading={busy}>Se connecter</Button>
          </Form>
        </Card>
      </div>
    </div>
  );
}
