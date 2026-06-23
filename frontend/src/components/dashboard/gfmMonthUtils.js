export const GFM_MONTH_ABBR = [
    'JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN',
    'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC',
];

/** Last N filing periods ending at the previous calendar month (MON-YYYY). */
export function generateGfmMonthOptions(count = 24) {
    const today = new Date();
    const anchor = new Date(today.getFullYear(), today.getMonth(), 0);
    const columns = [];
    let year = anchor.getFullYear();
    let month = anchor.getMonth();

    for (let i = 0; i < count; i += 1) {
        columns.push(`${GFM_MONTH_ABBR[month]}-${year}`);
        month -= 1;
        if (month < 0) {
            month = 11;
            year -= 1;
        }
    }
    return columns.reverse();
}

export function formatGfmPeriodLabel(period) {
    if (!period) return '—';
    const [mon, year] = String(period).split('-');
    if (!mon || !year) return period;
    return `${mon} '${String(year).slice(-2)}`;
}

function periodSortKey(period) {
    const [mon, year] = String(period).split('-');
    return [Number(year), GFM_MONTH_ABBR.indexOf(mon)];
}

export function normalizeGfmPeriodList(periods = [], optionCount = 24) {
    const allowed = new Set(generateGfmMonthOptions(optionCount));
    return [...new Set(
        (Array.isArray(periods) ? periods : [])
            .map((value) => String(value).trim().toUpperCase())
            .filter((value) => allowed.has(value)),
    )].sort((a, b) => {
        const [ay, am] = periodSortKey(a);
        const [by, bm] = periodSortKey(b);
        return ay - by || am - bm;
    });
}
