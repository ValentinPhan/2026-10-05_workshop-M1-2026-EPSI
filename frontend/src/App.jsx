import React from 'react';
import { Flex, Layout, Spin } from 'antd';
import { useAuth } from './hooks/useAuth.js';
import LoginPage from './components/LoginPage.jsx';
import Dashboard from './Dashboard.jsx';

// Porte d'entrée : rien du tableau de bord (ni données, ni WebSocket) n'est chargé sans compte connecté.
export default function App() {
  const { user, loading, login, logout } = useAuth();

  if (loading) {
    return (
      <Layout style={{ minHeight: '100vh' }}>
        <Flex justify="center" align="center" style={{ flex: 1 }}><Spin size="large" /></Flex>
      </Layout>
    );
  }
  return user ? <Dashboard user={user} onLogout={logout} /> : <LoginPage onLogin={login} />;
}
