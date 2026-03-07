/**
 * Shared API request helper.
 *
 * In dev mode, routes directly to the backend at localhost:3000.
 * In production, uses relative URLs (same origin, served by FastAPI).
 */

import { getToken } from '$lib/auth.js';

export const ORIGIN = import.meta.env.DEV ? 'http://localhost:3000' : '';

export async function request(path, options = {}) {
    const url = `${ORIGIN}${path}`;

    const headers = {
        'Content-Type': 'application/json',
        ...options.headers
    };

    const token = getToken();
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }

    const res = await fetch(url, { ...options, headers });

    if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(body.detail || `Request failed: ${res.status}`);
    }

    return res.json();
}
