// Appels à l'API. Les cookies de session partent automatiquement (même origine, via le proxy de Vite).
// Une réponse 401 (session expirée ou fermée) déclenche l'événement AUTH_EXPIRED : l'application revient à la
// page de connexion. Les erreurs portent le message du backend (`{error}`) et le code HTTP (`status`).
export const AUTH_EXPIRED = 'sentinel:auth-expired';

async function request(url, options) {
  const res = await fetch(url, { credentials: 'same-origin', ...options });
  if (!res.ok) {
    const message = (await res.json().catch(() => ({}))).error ?? res.statusText;
    if (res.status === 401 && url !== '/api/auth/login') window.dispatchEvent(new Event(AUTH_EXPIRED));
    throw Object.assign(new Error(message), { status: res.status });
  }
  return res.json();
}

export const getJson = (url) => request(url);
export const deleteJson = (url) => request(url, { method: 'DELETE' });
export const postJson = (url, body) =>
  request(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
