/** Normalize API scalar or array fields to string[]. */
export function asStringArray(value) {
    if (value == null || value === '') return [];
    if (Array.isArray(value)) {
        return value.map((v) => String(v).trim()).filter(Boolean);
    }
    return [String(value).trim()].filter(Boolean);
}

export function formatListDisplay(value, formatItem = (x) => x) {
    const items = asStringArray(value);
    if (!items.length) return '-';
    return items.map(formatItem).join(', ');
}

export const STANDARD_SOURCE_CODES = new Set([
    'SALARY',
    'BUSINESS',
    'PROFESSION',
    'CAPITAL_GAINS',
    'HOUSE_PROPERTY',
    'OTHER_SOURCES',
]);

export const INCOME_SOURCE_OPTIONS = [
    { value: 'SALARY', label: 'Salary' },
    { value: 'BUSINESS', label: 'Business' },
    { value: 'PROFESSION', label: 'Profession' },
    { value: 'CAPITAL_GAINS', label: 'Capital Gains' },
    { value: 'HOUSE_PROPERTY', label: 'House Property' },
    { value: 'OTHER_SOURCES', label: 'Other Sources' },
];

/** Preset income source codes sent to the API (excludes OTHER_SOURCES; added when needed). */
export const PAYLOAD_SOURCE_CODES = new Set([
    'SALARY',
    'BUSINESS',
    'PROFESSION',
    'CAPITAL_GAINS',
    'HOUSE_PROPERTY',
]);

/** Split API array into form state: standard toggles + custom labels. */
export function splitSourceOfIncome(value) {
    const items = asStringArray(value);
    const standard = [];
    const custom = [];
    let legacyOtherSourcesMarker = false;

    items.forEach((item) => {
        const code = item.toUpperCase();
        if (code === 'OTHER_SOURCES') {
            legacyOtherSourcesMarker = true;
            return;
        }
        if (PAYLOAD_SOURCE_CODES.has(code)) {
            if (!standard.includes(code)) standard.push(code);
        } else {
            const label = item.trim();
            if (label && !custom.includes(label)) custom.push(label);
        }
    });

    if (custom.length > 0 || legacyOtherSourcesMarker) {
        if (!standard.includes('OTHER_SOURCES')) standard.push('OTHER_SOURCES');
    }

    return { standard, custom };
}

/**
 * Build API payload: preset codes (SALARY, …) plus custom labels.
 * Custom labels are sent as-is (e.g. ["Computers Shop"]); OTHER_SOURCES is not required.
 */
export function buildSourceOfIncomePayload(standardCodes, customServices = []) {
    const codes = [...new Set(
        standardCodes.filter((c) => PAYLOAD_SOURCE_CODES.has(String(c).toUpperCase()))
    )];
    const customs = customServices.map((s) => s.trim()).filter(Boolean);
    const merged = [...codes];
    customs.forEach((label) => {
        const exists = merged.some((m) => m.toLowerCase() === label.toLowerCase());
        if (!exists) merged.push(label);
    });
    return merged.length ? merged : null;
}

/** Values to show in table/details (omit UI-only OTHER_SOURCES). */
export function sourceOfIncomeForDisplay(value) {
    return asStringArray(value).filter((item) => item.toUpperCase() !== 'OTHER_SOURCES');
}

const SOURCE_LABELS = {
    SALARY: 'Salary',
    BUSINESS: 'Business',
    PROFESSION: 'Profession',
    CAPITAL_GAINS: 'Capital Gains',
    HOUSE_PROPERTY: 'House Property',
    OTHER_SOURCES: 'Other Sources',
};

export function formatSourceItem(codeOrLabel) {
    const upper = String(codeOrLabel || '').trim().toUpperCase();
    if (SOURCE_LABELS[upper]) return SOURCE_LABELS[upper];
    return String(codeOrLabel || '').trim() || '-';
}

export function formatListDisplaySources(value) {
    const items = sourceOfIncomeForDisplay(value);
    if (!items.length) return '-';
    return items.map(formatSourceItem).join(', ');
}

/** Calendar year in IST (matches backend `current_income_tax_year`). */
export function getCurrentIstCalendarYear(referenceDate = new Date()) {
    const parts = new Intl.DateTimeFormat('en-IN', {
        timeZone: 'Asia/Kolkata',
        year: 'numeric',
    }).formatToParts(referenceDate);
    const yearPart = parts.find((p) => p.type === 'year');
    return yearPart ? parseInt(yearPart.value, 10) : referenceDate.getFullYear();
}

/** Latest FY start year allowed for filing in the given calendar year (IST). */
export function getMaxAllowedFinancialYearStart(referenceDate = new Date()) {
    return getCurrentIstCalendarYear(referenceDate) - 2;
}

export function parseFinancialYearStart(fy) {
    const m = /^(\d{4})-/.exec(String(fy).trim());
    return m ? parseInt(m[1], 10) : NaN;
}

/** e.g. 2024 → "2024-25" */
export function formatFinancialYearLabel(startYear) {
    const endSuffix = String((startYear + 1) % 100).padStart(2, '0');
    return `${startYear}-${endSuffix}`;
}

/** Quick-select FY pills — previous filing years only (no current/upcoming FY). */
export function buildFinancialYearPresetOptions({
    yearsBack = 5,
    referenceDate = new Date(),
} = {}) {
    const maxStart = getMaxAllowedFinancialYearStart(referenceDate);
    const out = [];
    for (let i = 0; i <= yearsBack; i += 1) {
        const start = maxStart - i;
        if (start < 2000) break;
        out.push(formatFinancialYearLabel(start));
    }
    return out;
}

export const COMMON_FINANCIAL_YEARS = buildFinancialYearPresetOptions({ yearsBack: 4 });

/** FY must be YYYY-YY where YY is the last two digits of (start year + 1). */
export function validateFinancialYearEncoding(fy) {
    const m = /^(\d{4})-(\d{2})$/.exec(String(fy).trim());
    if (!m) {
        return 'Financial Year must look like 2024-25 (four digits, hyphen, two digits).';
    }
    const start = parseInt(m[1], 10);
    const suffix = m[2];
    const expected = String((start + 1) % 100).padStart(2, '0');
    if (suffix !== expected) {
        return `Financial Year should be written as ${start}-${expected} (FY ${start}–${start + 1}). For example, use ${start}-${expected} instead of ${fy}.`;
    }
    return null;
}

/** Format + filing-window rule: only previous FYs for the current calendar year. */
export function validateFinancialYearAllowed(fy, referenceDate = new Date()) {
    const encodingErr = validateFinancialYearEncoding(fy);
    if (encodingErr) return encodingErr;

    const start = parseFinancialYearStart(fy);
    const maxStart = getMaxAllowedFinancialYearStart(referenceDate);
    const calYear = getCurrentIstCalendarYear(referenceDate);
    if (start > maxStart) {
        const maxLabel = formatFinancialYearLabel(maxStart);
        return (
            `In ${calYear}, you can file only for previous financial years (up to ${maxLabel}). `
            + `${fy} is the current or a future FY and cannot be added here.`
        );
    }
    return null;
}

/** Hint shown on create/edit — explains previous-years-only rule. */
export function getFinancialYearFormHint(referenceDate = new Date()) {
    const calYear = getCurrentIstCalendarYear(referenceDate);
    const maxLabel = formatFinancialYearLabel(getMaxAllowedFinancialYearStart(referenceDate));
    return (
        `In ${calYear}, add only previous FYs you are filing for (for example up to ${maxLabel}). `
        + 'Use format YYYY-YY. Current or upcoming years such as 2025-26 cannot be added on this form.'
    );
}
