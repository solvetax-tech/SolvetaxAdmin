/** SALARY → Salary, CAPITAL_GAINS → Capital Gains */
export function formatEnumLabel(value) {
    if (value == null || value === '') return '-';
    return String(value)
        .trim()
        .toLowerCase()
        .split('_')
        .filter(Boolean)
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
        .join(' ');
}

/**
 * Display API timestamps in Indian Standard Time with 12-hour clock.
 */
export function formatDateTimeIST(dtStr) {
    if (!dtStr) return '-';
    try {
        return new Date(dtStr).toLocaleString('en-IN', {
            timeZone: 'Asia/Kolkata',
            day: '2-digit',
            month: 'short',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            hour12: true,
        });
    } catch {
        return String(dtStr);
    }
}

export function formatDateIST(dtStr) {
    if (!dtStr) return '-';
    try {
        return new Date(dtStr).toLocaleDateString('en-IN', {
            timeZone: 'Asia/Kolkata',
            day: '2-digit',
            month: 'short',
            year: 'numeric',
        });
    } catch {
        return String(dtStr);
    }
}

/**
 * Convert date input (YYYY-MM-DD) to ISO-8601 with IST offset for API date filters.
 * @param {{ endOfDay?: boolean }} options — use endOfDay for inclusive "to" dates
 */
export function dateLocalToIstIso(value, { endOfDay = false } = {}) {
    if (!value || typeof value !== 'string') return '';
    const d = String(value).trim();
    if (!/^\d{4}-\d{2}-\d{2}$/.test(d)) return '';
    return `${d}T${endOfDay ? '23:59:59' : '00:00:00'}+05:30`;
}

/**
 * Convert datetime-local input value to ISO-8601 with IST offset for API filters.
 */
export function datetimeLocalToIstIso(value) {
    if (!value || typeof value !== 'string') return '';
    let iso = String(value).trim();
    if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(iso)) {
        iso += ':00';
    }
    if (!/[zZ]|[+-]\d{2}:\d{2}$/.test(iso)) {
        iso += '+05:30';
    }
    return iso;
}
