import React, { useEffect, useState } from 'react';
import { Sun, Moon } from 'lucide-react';
import { getTheme, toggleTheme, subscribeTheme } from '../../utils/themeManager';

/**
 * Sidebar footer toggle that flips the app between light and dark themes.
 * Styled as a standard `nav-item footer-item` so it matches the Profile /
 * Settings entries in both the Dashboard and CRM sidebars.
 */
export default function ThemeToggle() {
    const [theme, setThemeState] = useState(getTheme());

    useEffect(() => subscribeTheme(setThemeState), []);

    const isDark = theme === 'dark';
    const label = isDark ? 'Light Mode' : 'Dark Mode';

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
            <span className="nav-icon">{isDark ? <Sun size={18} /> : <Moon size={18} />}</span>
            <span className="nav-label">{label}</span>
        </div>
    );
}
