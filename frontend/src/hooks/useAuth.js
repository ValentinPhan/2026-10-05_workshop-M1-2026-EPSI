import { useCallback, useEffect, useState } from 'react';
import { AUTH_EXPIRED, getJson, postJson } from '../api.js';

// Utilisateur connecté ({ username, role: 'admin' | 'agent' }) d'après le cookie de session.
// `loading` : la vérification initiale (GET /api/auth/me) n'est pas terminée.
export function useAuth() {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getJson('/api/auth/me')
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
    const onExpired = () => setUser(null); // session expirée ou fermée côté serveur
    window.addEventListener(AUTH_EXPIRED, onExpired);
    return () => window.removeEventListener(AUTH_EXPIRED, onExpired);
  }, []);

  const login = useCallback(async (username, password) => setUser(await postJson('/api/auth/login', { username, password })), []);
  const logout = useCallback(async () => {
    try {
      await postJson('/api/auth/logout');
    } finally {
      setUser(null);
    }
  }, []);

  return { user, loading, login, logout };
}
