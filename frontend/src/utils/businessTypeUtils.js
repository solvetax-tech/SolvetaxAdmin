/** Config row value for the "Other" business type option. */
export function getOtherBusinessTypeValue(configItems = []) {
    const match = configItems.find((item) => {
        const v = String(item.value ?? item).trim().toUpperCase();
        const label = String(item.display_name || item.label || item.name || '').trim().toUpperCase();
        return v === 'OTHER' || label === 'OTHER';
    });
    return match != null ? (match.value ?? match) : 'OTHER';
}

export function isBusinessTypeOther(value, configItems = []) {
    if (value == null || value === '') return false;
    const otherVal = String(getOtherBusinessTypeValue(configItems)).trim().toUpperCase();
    const norm = String(value).trim().toUpperCase();
    return norm === otherVal || norm === 'OTHER';
}

/** API value: custom text when provided, else canonical Other when Other is selected. */
export function resolveBusinessTypeForApi(selectedType, otherText, configItems = []) {
    if (!isBusinessTypeOther(selectedType, configItems)) {
        const trimmed = typeof selectedType === 'string' ? selectedType.trim() : selectedType;
        return trimmed || null;
    }
    const custom = String(otherText ?? '').trim();
    if (custom) return custom;
    return String(getOtherBusinessTypeValue(configItems)).trim() || 'OTHER';
}

/** Map stored API value back to dropdown + optional custom text field. */
export function parseBusinessTypeFromApi(storedValue, configItems = []) {
    if (storedValue == null || storedValue === '') {
        return { selectValue: '', otherText: '' };
    }
    const stored = String(storedValue).trim();
    const known = configItems.find((item) => {
        const v = String(item.value ?? item).trim();
        return v.toUpperCase() === stored.toUpperCase();
    });
    if (known) {
        return { selectValue: known.value ?? known, otherText: '' };
    }
    return {
        selectValue: getOtherBusinessTypeValue(configItems),
        otherText: stored,
    };
}
