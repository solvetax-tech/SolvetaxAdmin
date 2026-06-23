/**
 * @file api.js
 * @description Centralized Axios instance configuration.
 * Handles automatic JWT injection into request headers and 
 * provides response interceptors for 401/403 token refresh logic.
 */
import axios from 'axios';
import {
    getPublicApiKey,
    requiresPublicApiKey,
    resolveRequestPathname,
} from './publicApiKey';

const api = axios.create({
    baseURL: import.meta.env.VITE_API_URL || '',
    withCredentials: true,
});

// Request interceptor: JWT + public API key on designated routes
api.interceptors.request.use(
    (config) => {
        const token = localStorage.getItem('session_token');
        if (token) {
            config.headers['Authorization'] = `Bearer ${token}`;
        }

        const publicKey = getPublicApiKey();
        if (publicKey) {
            const pathname = resolveRequestPathname(config.url, config.baseURL);
            if (requiresPublicApiKey(pathname)) {
                config.headers['X-Public-Api-Key'] = publicKey;
            }
        }

        return config;
    },
    (error) => Promise.reject(error)
);

// Response interceptor to handle 401s and standardize error messages
api.interceptors.response.use(
    (response) => response,
    async (error) => {
        if (axios.isCancel(error) || error.name === 'CanceledError') {
            return Promise.reject(error);
        }

        const originalRequest = error.config || {};
        const isAuthError = error.response?.status === 401;
        const detail = error.response?.data?.detail;
        const isTokenExpiredError =
            error.response?.status === 403 &&
            typeof detail === 'string' &&
            detail.includes('Token expired');

        if ((isAuthError || isTokenExpiredError) && !originalRequest._retry && originalRequest.url !== '/app/v1/refresh') {
            originalRequest._retry = true;
            try {
                const rs = await api.post('/app/v1/refresh', {}, {
                    headers: { 'Content-Type': 'application/json' },
                    withCredentials: true
                });
                const { access_token } = rs.data;
                if (access_token) {
                    localStorage.setItem('session_token', access_token);
                    originalRequest.headers['Authorization'] = `Bearer ${access_token}`;
                    return api(originalRequest);
                }
            } catch (refreshError) {
                localStorage.removeItem('session_token');
                if (window.location.pathname !== '/login') {
                    window.location.href = '/login';
                }
            }
        }

        // --- Structured backend error handling (aligned with FastAPI responses) ---
        let errorMessage = 'Operation failed';
        let fieldErrors = {};

        if (error.response) {
            const data = error.response.data || {};

            // Primary backend format
            // { error: { type, message, fields } }
            if (data?.error) {
                fieldErrors = data.error.fields || {};

                if (Object.keys(fieldErrors).length > 0) {
                    // Combine field error messages
                    errorMessage = Object.values(fieldErrors).join('\n');
                } else {
                    errorMessage = data.error.message || errorMessage;
                }
            }

            // Wrapped FastAPI format
            // { detail: { error: { ... } } }
            else if (data?.detail?.error) {
                fieldErrors = data.detail.error.fields || {};

                if (Object.keys(fieldErrors).length > 0) {
                    errorMessage = Object.values(fieldErrors).join('\n');
                } else {
                    errorMessage = data.detail.error.message || errorMessage;
                }
            }

            // FastAPI simple detail string
            else if (typeof data?.detail === 'string') {
                errorMessage = data.detail;
            }

            // FastAPI/Pydantic validation list
            // { detail: [{ loc: [...], msg: "...", type: "..." }, ...] }
            else if (Array.isArray(data?.detail)) {
                const details = data.detail;
                const normalizedFields = {};

                details.forEach((entry, index) => {
                    const loc = Array.isArray(entry?.loc) ? entry.loc : [];
                    const field = loc.length > 0 ? String(loc[loc.length - 1]) : `field_${index}`;
                    const msg = entry?.msg || 'Invalid value';
                    normalizedFields[field] = msg;
                });

                fieldErrors = normalizedFields;
                const messages = Object.values(normalizedFields);
                errorMessage = messages.length > 0 ? messages.join('\n') : errorMessage;
            }

            // Legacy object detail
            else if (typeof data?.detail === 'object') {
                errorMessage = data.detail.message || errorMessage;
                fieldErrors = data.detail.fields || {};
            }
        } else if (error.message) {
            errorMessage = error.message;
        }

        const customError = new Error(errorMessage);
        customError.status = error.response?.status;
        customError.fields = fieldErrors;
        customError.response = error.response;
        customError.data = error.response?.data;
        customError.originalError = error;

        return Promise.reject(customError);
    }
);

// We keep `fetchWithAuth` wrapper for backwards compatibility with any remaining unrefactored fetches 
// during the transition period, but ideally we'll replace all usages and delete this.
export const fetchWithAuth = async (url, options = {}) => {
    try {
        const response = await api({
            url: url.replace(import.meta.env.VITE_API_URL, ''), // api is already prefixed
            method: options.method || 'GET',
            data: typeof options.body === 'string'
                ? JSON.parse(options.body)
                : options.body,
            headers: options.headers
        });

        // Mock a native Response object for older code expecting it
        return {
            ok: true,
            status: response.status,
            json: async () => response.data,
            headers: new Headers(response.headers)
        };
    } catch (error) {
        return {
            ok: false,
            status: error.status || 500,
            statusText: error.message,
            json: async () => ({ detail: error.message })
        };
    }
};

export default api;
