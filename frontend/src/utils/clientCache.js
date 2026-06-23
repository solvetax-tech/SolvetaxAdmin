/**
 * @file clientCache.js
 * @description Lightweight, dependency-free in-memory cache with TTL,
 * stale-while-revalidate behavior, and in-flight request de-duplication.
 *
 * Goal: stop re-fetching shared/reference data every time the user navigates
 * between tabs. Frequently used GETs (RM/OP lists, service options, configs)
 * are cached for a short TTL so revisiting a screen is instant, while the
 * data still refreshes once it goes stale.
 *
 * This is intentionally NOT a "load everything at login" approach — heavy,
 * paginated, or filter-dependent endpoints stay lazy. Only small, shared
 * reference data flows through here (plus an optional login-time prefetch).
 */

const DEFAULT_TTL_MS = 120000; // 2 minutes

/** @type {Map<string, { value: any, expiresAt: number, promise: Promise<any> | null }>} */
const store = new Map();

/**
 * Get a value from cache or load it. Fresh entries are returned immediately,
 * concurrent callers share a single in-flight request, and a failed load keeps
 * any previously cached (stale) value instead of poisoning the cache.
 *
 * @param {string} key Unique cache key.
 * @param {() => Promise<any>} loader Async loader invoked on cache miss.
 * @param {{ ttlMs?: number, force?: boolean }} [options]
 * @returns {Promise<any>}
 */
export async function cachedGet(key, loader, { ttlMs = DEFAULT_TTL_MS, force = false } = {}) {
    const now = Date.now();
    const entry = store.get(key);

    if (!force && entry) {
        if (entry.value !== undefined && entry.expiresAt > now) {
            return entry.value; // fresh hit
        }
        if (entry.promise) {
            return entry.promise; // de-dupe concurrent loads
        }
    }

    const promise = Promise.resolve()
        .then(loader)
        .then((value) => {
            store.set(key, { value, expiresAt: Date.now() + ttlMs, promise: null });
            return value;
        })
        .catch((err) => {
            const prev = store.get(key);
            if (prev) {
                prev.promise = null; // keep stale value if any, drop the failed promise
            } else {
                store.delete(key);
            }
            throw err;
        });

    store.set(key, {
        value: entry ? entry.value : undefined,
        expiresAt: entry ? entry.expiresAt : 0,
        promise,
    });
    return promise;
}

/**
 * Fire-and-forget warm-up. Never throws; used by the login-time prefetch.
 * @param {string} key
 * @param {() => Promise<any>} loader
 * @param {{ ttlMs?: number, force?: boolean }} [options]
 */
export function prefetch(key, loader, options) {
    cachedGet(key, loader, options).catch(() => {});
}

/** Drop a single cache entry (e.g. after a mutation that changes it). */
export function invalidate(key) {
    store.delete(key);
}

/** Drop every entry whose key starts with the given prefix. */
export function invalidatePrefix(prefix) {
    for (const key of store.keys()) {
        if (key.startsWith(prefix)) store.delete(key);
    }
}

/** Wipe the whole cache — call on logout so the next user starts clean. */
export function clearClientCache() {
    store.clear();
}
