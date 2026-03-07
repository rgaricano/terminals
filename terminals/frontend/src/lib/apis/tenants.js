import { request } from './index.js';

const BASE = '/api/v1/tenants';

export async function fetchTenants() {
    return request(`${BASE}/`);
}

export async function fetchTenant(userId) {
    return request(`${BASE}/${encodeURIComponent(userId)}`);
}

export async function createTenant(userId) {
    return request(`${BASE}/`, {
        method: 'POST',
        headers: { 'X-User-Id': userId }
    });
}

export async function deleteTenant(userId) {
    return request(`${BASE}/${encodeURIComponent(userId)}`, {
        method: 'DELETE'
    });
}

export async function startTenant(userId) {
    return request(`${BASE}/${encodeURIComponent(userId)}/start`, {
        method: 'POST'
    });
}

export async function stopTenant(userId) {
    return request(`${BASE}/${encodeURIComponent(userId)}/stop`, {
        method: 'POST'
    });
}
