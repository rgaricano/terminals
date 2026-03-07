/**
 * Open WebUI auth API client.
 *
 * Signs in against a user-provided Open WebUI instance to get a JWT,
 * then validates that JWT to retrieve user info.
 */

export async function signinOpenWebUI(baseUrl, email, password) {
    const res = await fetch(`${baseUrl}/api/v1/auths/signin`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password })
    });

    if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(body.detail || 'Sign in failed');
    }

    return res.json(); // { token, token_type, id, email, name, role, ... }
}

export async function verifyOpenWebUI(baseUrl, token) {
    const res = await fetch(`${baseUrl}/api/v1/auths/`, {
        headers: { 'Authorization': `Bearer ${token}` }
    });

    if (!res.ok) {
        throw new Error('Token validation failed');
    }

    return res.json(); // { id, email, name, role, profile_image_url, ... }
}
