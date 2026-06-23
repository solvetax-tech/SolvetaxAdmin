/** Config rows without a leading empty option. */
export function optionsFromConfigOnly(items = []) {
    return items.map((item) => ({
        value: item.value ?? item,
        label: item.display_name || item.label || item.name || String(item.value ?? item),
    }));
}

/** Build CustomSelect options from API config rows ({ value, display_name }). */
export function optionsFromConfig(items = [], placeholderLabel = 'Select') {
    return [
        { value: '', label: placeholderLabel },
        ...items.map((item) => ({
            value: item.value ?? item,
            label: item.display_name || item.label || item.name || String(item.value ?? item),
        })),
    ];
}

/** Build options from { value, label } pairs (e.g. buildRmOpIdSelectOptions). */
export function optionsFromPairs(pairs = [], placeholderLabel = 'Select') {
    const hasEmpty = pairs.some((p) => p.value === '' || p.value === null || p.value === undefined);
    const list = pairs.map((p) => ({
        value: p.value,
        label: p.label ?? String(p.value),
    }));
    return hasEmpty ? list : [{ value: '', label: placeholderLabel }, ...list];
}

/** Synthetic event for legacy handleChange(e) that reads e.target.name / e.target.value. */
export function syntheticSelectEvent(name, value) {
    return { target: { name, value } };
}
