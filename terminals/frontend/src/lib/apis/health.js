import { request, ORIGIN } from './index.js';

export async function healthCheck() {
    return request('/health');
}
