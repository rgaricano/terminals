/**
 * Auth store - persists connection settings and user session.
 *
 * Supports two auth modes:
 *   1. Open WebUI - signs in via an Open WebUI instance, gets a JWT
 *   2. API Key    - direct TERMINALS_API_KEY (no user info)
 *   3. None       - no auth configured (open access)
 */

const STORAGE_KEY = 'terminals_auth';

function load() {
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        return raw ? JSON.parse(raw) : null;
    } catch {
        return null;
    }
}

function save(data) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
}

export function getAuth() {
    return load();
}

export function getToken() {
    const auth = load();
    return auth?.token || '';
}

export function getOpenWebUIUrl() {
    const auth = load();
    return auth?.openWebUIUrl || '';
}

export function getUser() {
    const auth = load();
    return auth?.user || null;
}

export function isAuthenticated() {
    const auth = load();
    if (!auth) return false;
    if (auth.mode === 'open-webui') return !!auth.token;
    if (auth.mode === 'api-key') return !!auth.token;
    return false;
}

export function getAuthMode() {
    const auth = load();
    return auth?.mode || null;
}

export function saveOpenWebUIAuth(openWebUIUrl, token, user) {
    save({ mode: 'open-webui', openWebUIUrl, token, user });
}

export function saveApiKeyAuth(token) {
    save({ mode: 'api-key', token, user: null });
}

export function clearAuth() {
    localStorage.removeItem(STORAGE_KEY);
}
