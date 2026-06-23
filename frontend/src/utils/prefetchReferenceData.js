/**
 * @file prefetchReferenceData.js
 * @description Warms the client cache with small, shared reference data right
 * after a confirmed login (token present). This is the "feels instant" layer:
 * the lists/configs used across many screens are fetched once in the background
 * so the first navigation into those screens has no spinner.
 *
 * Deliberately scoped to lightweight, role-agnostic reference data. Heavy,
 * paginated, or filter-dependent endpoints are intentionally NOT prefetched —
 * they stay lazy and are cached per request where appropriate.
 */
import { fetchActiveRmEmployees, fetchActiveOpEmployees } from './activeEmployees';
import { fetchStaffServiceConfig } from './staffServiceConfigApi';
import { fetchContactSupportOptions } from './contactSupportApi';
import { fetchIncomeTaxConfigs } from './incomeTaxConfigs';

let started = false;

function runWhenIdle(fn) {
    if (typeof window !== 'undefined' && typeof window.requestIdleCallback === 'function') {
        window.requestIdleCallback(fn, { timeout: 2000 });
    } else {
        setTimeout(fn, 0);
    }
}

/**
 * Kick off background prefetch of shared reference data. Safe to call multiple
 * times — it only runs once per session and never throws.
 *
 * @param {{ force?: boolean }} [options] force=true re-runs even if already started.
 */
export function prefetchReferenceData({ force = false } = {}) {
    if (started && !force) return;
    if (typeof localStorage !== 'undefined' && !localStorage.getItem('session_token')) {
        return; // only prefetch for authenticated sessions
    }
    started = true;

    runWhenIdle(() => {
        // Each is independent and self-caching; swallow errors so a single
        // failed prefetch never affects the others or the UI.
        Promise.allSettled([
            fetchActiveRmEmployees(),
            fetchActiveOpEmployees(),
            fetchStaffServiceConfig(),
            fetchContactSupportOptions(),
            fetchIncomeTaxConfigs(),
        ]).catch(() => {});
    });
}

/** Reset the "already started" guard (call on logout). */
export function resetReferenceDataPrefetch() {
    started = false;
}
