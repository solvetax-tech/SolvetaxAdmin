/**
 * Backend routes that require X-Public-Api-Key (VITE_PUBLIC_API_KEY).
 * Must stay in sync with server public_api_key_paths.
 */
export const PUBLIC_API_KEY_PATHS = [
    '/api/v1/crm/leads/marketing',
    '/api/v1/customers',
    '/api/v1/contact-support',
    '/api/v1/event-logs',
    '/api/v1/event-logs/debug/smoke',
    '/api/v1/payments_config/payment-config/public',
    '/api/v1/payments_config/payment-config/public/service-prices',
];

export function getPublicApiKey() {
    return import.meta.env.VITE_PUBLIC_API_KEY || '';
}

/** Normalize axios/fetch URL to pathname (no query string). */
export function resolveRequestPathname(url, baseURL = '') {
    if (!url) return '';
    const raw = String(url).split('?')[0];

    try {
        if (/^https?:\/\//i.test(raw)) {
            return new URL(raw).pathname.replace(/\/+$/, '') || '/';
        }
        const base = baseURL || import.meta.env.VITE_API_URL || 'http://localhost';
        const normalizedBase = base.endsWith('/') ? base : `${base}/`;
        const path = raw.startsWith('/') ? raw.slice(1) : raw;
        return new URL(path, normalizedBase).pathname.replace(/\/+$/, '') || '/';
    } catch {
        const path = raw.startsWith('/') ? raw : `/${raw}`;
        return path.replace(/\/+$/, '') || '/';
    }
}

export function requiresPublicApiKey(pathname) {
    const path = resolveRequestPathname(pathname);
    return PUBLIC_API_KEY_PATHS.some(
        (entry) => path === entry.replace(/\/+$/, ''),
    );
}

export function withPublicApiKeyHeaders(headers = {}) {
    const key = getPublicApiKey();
    if (!key) return headers;
    return {
        ...headers,
        'X-Public-Api-Key': key,
    };
}
