import React, { useEffect, useState } from 'react';
import { Sun, Moon, Palette } from 'lucide-react';
import {
    getTheme,
    nextTheme,
    toggleTheme,
    subscribeTheme,
    THEME_LABELS,
} from '../../utils/themeManager';

/** Icon per theme, keyed by the theme the toggle would switch TO. */
const ICONS = {
    dark: Moon,
    light: Sun,
    violet: Palette,
};

/**
 * Sidebar footer control that cycles the app through its themes
 * (Dark → White → Violet). It is labelled with the theme it switches TO, so
 * the next click is predictable. Styled as a standard `nav-item footer-item`
 * so it matches the Profile / Settings entries in both the Dashboard and CRM
 * sidebars.
 */
export default function ThemeToggle() {
    const [theme, setThemeState] = useState(getTheme());

    useEffect(() => subscribeTheme(setThemeState), []);

    // Advertise the destination, not the current state.
    const next = nextTheme(theme);
    const Icon = ICONS[next] || Sun;
    const label = `${THEME_LABELS[next]} Mode`;

    return (
        <div
            className="nav-item footer-item theme-toggle-item"
            onClick={() => toggleTheme()}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    toggleTheme();
                }
            }}
            title={label}
            aria-label={label}
        >
            <span className="nav-icon"><Icon size={18} /></span>
            <span className="nav-label">{label}</span>
        </div>
    );
}
