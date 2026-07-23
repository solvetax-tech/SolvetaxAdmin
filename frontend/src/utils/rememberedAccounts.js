/**
 * "Remembered accounts" for the profile account-switcher (the profile dropdown
 * in Dashboard).
 *
 * SECURITY: this list is a convenience only. It stores NO passwords and NO
 * tokens — just enough to show the account and pre-fill the login email
 * (emp_id, email, name, role). Switching still requires the account's password,
 * so the httpOnly refresh-token model is never weakened. Persisted per device
 * in localStorage.
 */

const STORAGE_KEY = 'remembered_accounts';
const MAX_ACCOUNTS = 6;

export function getRememberedAccounts() {
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        const list = raw ? JSON.parse(raw) : [];
        if (!Array.isArray(list)) return [];
        return list
            .filter((a) => a && a.email)
            .sort((a, b) => (b.last_used || 0) - (a.last_used || 0));
    } catch {
        return [];
    }
}

/**
 * Add or refresh an account in the list. Deduped by emp_id and email; the most
 * recently used account sorts first. Never stores secrets.
 */
export function rememberAccount(account) {
    if (!account?.email) return;
    const email = String(account.email).trim().toLowerCase();
    if (!email) return;

    const entry = {
        emp_id: account.emp_id ?? null,
        email,
        name: (account.name || '').trim(),
        role: account.role || '',
        last_used: Date.now(),
    };

    const others = getRememberedAccounts().filter(
        (a) => a.email !== email && String(a.emp_id) !== String(entry.emp_id)
    );
    const next = [entry, ...others].slice(0, MAX_ACCOUNTS);

    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
        /* quota / private mode — remembering is best-effort */
    }
}

/** Drop one account from the list (by email). */
export function removeRememberedAccount(email) {
    const key = String(email || '').trim().toLowerCase();
    const next = getRememberedAccounts().filter((a) => a.email !== key);
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
        /* ignore */
    }
}
