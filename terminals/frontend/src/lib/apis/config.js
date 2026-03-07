import { request } from './index.js';

export async function fetchConfig() {
    return request('/api/v1/config');
}

export async function fetchStats() {
    return request('/api/v1/stats');
}
