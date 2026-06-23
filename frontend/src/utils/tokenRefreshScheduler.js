/**
 * @file tokenRefreshScheduler.js
 * @description Proactive access-token refresh.
 *
 * The access token (JWT) lives ~60 min and the refresh token lives in an
 * httpOnly cookie (see backend app/sign_up/login.py). Instead of waiting for a
 * 401 to trigger a reactive refresh, this scheduler calls POST /app/v1/refresh
 * a few minutes BEFORE the current token expires, stores the new token, and
 * reschedules off the new token's real `exp`. The browser sends the refresh
 * cookie automatically because the axios instance uses `withCredentials`.
 *
 * The existing 401/403 response interceptor in api.js stays as a safety net.
 */
import api from './api';

const REFRESH_SKEW_MS = 5 * 60 * 1000; // refresh 5 minutes before expiry
const MIN_DELAY_MS = 10 * 1000; // never schedule sooner than 10s
const FALLBACK_DELAY_MS = 55 * 60 * 1000; // if exp can't be read, use 55 min
const RETRY_DELAY_MS = 60 * 1000; // transient failure → retry in 1 min

let timerId = null;
let onAuthFailure = null;

/** Decode a JWT payload without verifying the signature (client-side only). */
function decodeJwtPayload(token) {
    try {
        const base64Url = token.split('.')[1];
        const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
        return JSON.parse(window.atob(base64));
    } catch {
        return null;
    }
}

/** Milliseconds until we should refresh the given token (exp − skew). */
function delayUntilRefresh(token) {
    const payload = decodeJwtPayload(token);
    if (!payload || !payload.exp) return FALLBACK_DELAY_MS;
    const expMs = payload.exp * 1000;
    const delay = expMs - Date.now() - REFRESH_SKEW_MS;
    return Math.max(delay, MIN_DELAY_MS);
}

function clearTimer() {
    if (timerId) {
        clearTimeout(timerId);
        timerId = null;
    }
}

/** Perform a refresh now; returns the new token or null on failure. */
async function doRefresh() {
    try {
        const res = await api.post('/app/v1/refresh', {}, {
            headers: { 'Content-Type': 'application/json' },
            withCredentials: true,
        });
        const newToken = res.data?.access_token;
        if (newToken) {
            localStorage.setItem('session_token', newToken);
            return newToken;
        }
        return null;
    } catch (err) {
        // 401/expired → refresh token is dead; force re-auth.
        if (err?.status === 401) {
            if (typeof onAuthFailure === 'function') onAuthFailure();
            return null;
        }
        // Transient (network/5xx) → caller will retry.
        throw err;
    }
}

function scheduleNext(token) {
    clearTimer();
    const current = token || localStorage.getItem('session_token');
    if (!current) return;

    const delay = delayUntilRefresh(current);
    timerId = setTimeout(async () => {
        try {
            const newToken = await doRefresh();
            if (newToken) {
                scheduleNext(newToken); // reschedule off the fresh token
            }
            // if null (auth failure), onAuthFailure already handled it
        } catch {
            // transient failure — try again shortly without logging the user out
            clearTimer();
            timerId = setTimeout(() => scheduleNext(), RETRY_DELAY_MS);
        }
    }, delay);
}

/**
 * Start (or restart) the proactive refresh loop. Idempotent.
 * @param {{ onAuthFailure?: () => void }} [options] called when the refresh
 *        token is rejected (so the app can log the user out).
 */
export function startTokenRefreshScheduler(options = {}) {
    if (typeof options.onAuthFailure === 'function') {
        onAuthFailure = options.onAuthFailure;
    }
    if (!localStorage.getItem('session_token')) return;
    scheduleNext();
}

/** Stop the refresh loop (call on logout). */
export function stopTokenRefreshScheduler() {
    clearTimer();
    onAuthFailure = null;
}

/**
 * If the current token is already past (or near) expiry — e.g. the laptop was
 * asleep — refresh immediately, otherwise just make sure a timer is scheduled.
 * Wire this to the `visibilitychange` / focus event.
 */
export async function refreshIfStale() {
    const token = localStorage.getItem('session_token');
    if (!token) return;
    const delay = delayUntilRefresh(token);
    if (delay <= MIN_DELAY_MS) {
        try {
            const newToken = await doRefresh();
            scheduleNext(newToken || token);
        } catch {
            scheduleNext(token);
        }
    } else if (!timerId) {
        scheduleNext(token);
    }
}
