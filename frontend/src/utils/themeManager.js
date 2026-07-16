/**
 * @file themeManager.js
 * @description Single source of truth for the app's theme.
 *
 * Three themes: dark, light (neutral white) and violet (the light palette
 * with a violet cast). Applied by setting `data-theme` on the document root
 * (<html>). All component CSS reads theme tokens (CSS custom properties)
 * defined in index.css, so flipping the attribute re-themes the whole app
 * instantly. The choice persists in localStorage.
 */

const STORAGE_KEY = 'solvetax_theme';
const DEFAULT_THEME = 'dark';

/** Every theme, in the order the toggle cycles through them. */
export const THEMES = ['dark', 'light', 'violet'];

/** Human labels for the toggle. */
export const THEME_LABELS = {
    dark: 'Dark',
    light: 'White',
    violet: 'Violet',
};

const VALID = new Set(THEMES);

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

/** Advance to the next theme in the cycle (dark → light → violet → dark). */
export function toggleTheme() {
    const i = THEMES.indexOf(getTheme());
    return setTheme(THEMES[(i + 1) % THEMES.length]);
}

/**
 * The theme the toggle would move to next — for labelling the control.
 * @param {string} [current] Defaults to the persisted theme.
 */
export function nextTheme(current) {
    const i = THEMES.indexOf(VALID.has(current) ? current : getTheme());
    return THEMES[(i + 1) % THEMES.length];
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
