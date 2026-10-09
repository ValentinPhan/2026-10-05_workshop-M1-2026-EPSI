import { Flex, Spin } from 'antd';
import { useAuth } from './hooks/useAuth.js';
import LoginPage from './components/LoginPage.jsx';
import Dashboard from './Dashboard.jsx';

// Porte d'entrée : rien du tableau de bord (ni données, ni WebSocket) n'est chargé sans compte connecté.
export default function App() {
  const { user, loading, login, logout } = useAuth();

  if (loading) {
    return (
      <div className="app-shell">
        <Flex justify="center" align="center" style={{ minHeight: '100vh' }}><Spin size="large" /></Flex>
      </div>
    );
  }
  return user ? <Dashboard user={user} onLogout={logout} /> : <LoginPage onLogin={login} />;
}
