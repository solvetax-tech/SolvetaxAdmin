/**
 * @file themeManager.js
 * @description Single source of truth for the app's light/dark theme.
 *
 * The theme is applied by setting `data-theme="light|dark"` on the document
 * root (<html>). All component CSS reads theme tokens (CSS custom properties)
 * defined in index.css, so flipping the attribute re-themes the whole app
 * instantly. The choice persists in localStorage.
 */

const STORAGE_KEY = 'solvetax_theme';
const DEFAULT_THEME = 'dark';
const VALID = new Set(['light', 'dark']);

const listeners = new Set();

/** Read the persisted theme, falling back to the default (dark). */
export function getTheme() {
    try {
        const stored = localStorage.getItem(STORAGE_KEY);
        if (stored && VALID.has(stored)) return stored;
    } catch {
        /* ignore storage errors */
    }
    return DEFAULT_THEME;
}

/** Apply a theme to <html> and persist it. */
export function setTheme(theme) {
    const next = VALID.has(theme) ? theme : DEFAULT_THEME;
    if (typeof document !== 'undefined') {
        document.documentElement.setAttribute('data-theme', next);
    }
    try {
        localStorage.setItem(STORAGE_KEY, next);
    } catch {
        /* ignore storage errors */
    }
    listeners.forEach((fn) => {
        try {
            fn(next);
        } catch {
            /* ignore listener errors */
        }
    });
    return next;
}

/** Flip between light and dark, returning the new theme. */
export function toggleTheme() {
    return setTheme(getTheme() === 'dark' ? 'light' : 'dark');
}

/**
 * Apply the persisted theme to the document. Call once as early as possible
 * (before first paint) to avoid a flash of the wrong theme.
 */
export function initTheme() {
    const theme = getTheme();
    if (typeof document !== 'undefined') {
        document.documentElement.setAttribute('data-theme', theme);
    }
    return theme;
}

/**
 * Subscribe to theme changes. Returns an unsubscribe function.
 * @param {(theme: string) => void} fn
 */
export function subscribeTheme(fn) {
    listeners.add(fn);
    return () => listeners.delete(fn);
}
