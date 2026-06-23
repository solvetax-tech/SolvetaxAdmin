import api from './api';
import { cachedGet } from './clientCache';

/** Cache keys for active RM/OP reference lists (small, shared, prefetchable). */
export const ACTIVE_RM_CACHE_KEY = 'employees:active-rm';
export const ACTIVE_OP_CACHE_KEY = 'employees:active-op';

/**
 * Parse GET /api/v1/employees/active-rm and active-op.
 * API returns [{ emp_id, username }, ...] (or legacy username-only rows).
 */
export function parseActiveEmployeesFromApi(res) {
    const body = res?.data;
    let list = [];
    if (Array.isArray(body)) {
        list = body;
    } else if (body && typeof body === 'object') {
        if (Array.isArray(body.data)) list = body.data;
        else if (Array.isArray(body.items)) list = body.items;
        else if (Array.isArray(body.usernames)) list = body.usernames;
    }

    const employees = [];
    const seen = new Set();

    for (const item of list) {
        if (typeof item === 'string') {
            const username = item.trim();
            if (!username || seen.has(`u:${username}`)) continue;
            seen.add(`u:${username}`);
            employees.push({ emp_id: null, username });
            continue;
        }
        if (!item || typeof item !== 'object') continue;
        const username = String(item.username || '').trim();
        if (!username) continue;
        const empId = item.emp_id != null && item.emp_id !== '' ? Number(item.emp_id) : null;
        const key = empId != null ? `id:${empId}` : `u:${username}`;
        if (seen.has(key)) continue;
        seen.add(key);
        employees.push({
            emp_id: Number.isFinite(empId) && empId > 0 ? empId : null,
            username,
        });
    }

    return employees.sort((a, b) =>
        a.username.localeCompare(b.username, undefined, { sensitivity: 'base' }),
    );
}

/** @deprecated Use parseActiveEmployeesFromApi — usernames only (filters). */
export function parseActiveUsernamesFromApi(res) {
    return parseActiveEmployeesFromApi(res).map((row) => row.username);
}

export async function fetchActiveRmEmployees({ force = false } = {}) {
    return cachedGet(
        ACTIVE_RM_CACHE_KEY,
        async () => parseActiveEmployeesFromApi(await api.get('/api/v1/employees/active-rm')),
        { force },
    );
}

export async function fetchActiveOpEmployees({ force = false } = {}) {
    return cachedGet(
        ACTIVE_OP_CACHE_KEY,
        async () => parseActiveEmployeesFromApi(await api.get('/api/v1/employees/active-op')),
        { force },
    );
}

/** Staff assignment dropdowns: fetch only the lists the form actually shows. */
export async function fetchAssignmentListsIfNeeded({ needRm = false, needOp = false } = {}) {
    const result = { activeRMs: [], activeOps: [] };
    const tasks = [];
    if (needRm) {
        tasks.push(
            fetchActiveRmEmployees().then((rows) => {
                result.activeRMs = rows;
            }),
        );
    }
    if (needOp) {
        tasks.push(
            fetchActiveOpEmployees().then((rows) => {
                result.activeOps = rows;
            }),
        );
    }
    if (tasks.length > 0) await Promise.all(tasks);
    return result;
}

/** @deprecated Prefer fetchAssignmentListsIfNeeded — always hits both endpoints. */
export async function fetchActiveRmOpEmployeeLists() {
    const [activeRMs, activeOps] = await Promise.all([
        fetchActiveRmEmployees(),
        fetchActiveOpEmployees(),
    ]);
    return { activeRMs, activeOps };
}

export async function fetchActiveRmUsernames() {
    return (await fetchActiveRmEmployees()).map((row) => row.username);
}

export async function fetchActiveOpUsernames() {
    return (await fetchActiveOpEmployees()).map((row) => row.username);
}

/** Load both RM and OP username lists (list filters only). */
export async function fetchActiveRmOpUsernameLists() {
    const [activeRMs, activeOps] = await Promise.all([
        fetchActiveRmUsernames(),
        fetchActiveOpUsernames(),
    ]);
    return { activeRMs, activeOps };
}

/** SearchableDropdown / CustomSelect options: value and label are both username. */
export function usernameDropdownOptions(usernames) {
    return (Array.isArray(usernames) ? usernames : []).map((username) => ({
        value: username,
        label: username,
    }));
}

/** Bulk-assign / filter dropdowns where the API expects emp_id query params. */
export function employeeIdDropdownOptions(employees) {
    return (Array.isArray(employees) ? employees : [])
        .filter((row) => row?.emp_id != null && Number(row.emp_id) > 0)
        .map((row) => ({
            value: Number(row.emp_id),
            label: row.username,
        }));
}

function isUsernameOnlyEntry(item) {
    if (typeof item === 'string') return true;
    return Boolean(
        item && typeof item === 'object' && item.username && (item.emp_id == null || item.emp_id === ''),
    );
}

/** CRM filter drawer: active-rm/op username lists, or legacy full employee objects. */
export function toEmployeeFilterOptions(employees, anyLabel) {
    if (!Array.isArray(employees) || employees.length === 0) {
        return [{ value: '', label: anyLabel }];
    }
    if (isUsernameOnlyEntry(employees[0])) {
        return [
            { value: '', label: anyLabel },
            ...usernameDropdownOptions(parseActiveUsernamesFromApi({ data: employees })),
        ];
    }
    const sorted = [...employees].sort((a, b) =>
        employeeDisplayName(a).localeCompare(employeeDisplayName(b), undefined, { sensitivity: 'base' })
    );
    return [
        { value: '', label: anyLabel },
        ...sorted.map((emp) => ({
            value: String(emp.emp_id),
            label: employeeDisplayName(emp),
        })),
    ];
}

function employeeDisplayName(emp) {
    const fullName = [emp.first_name, emp.last_name].filter(Boolean).join(' ').trim();
    if (fullName) return fullName;
    return emp.username || emp.email || `Employee ${emp.emp_id}`;
}

/** Full employee rows from GET /employees/filter (objects with emp_id). */
export function unwrapEmployeeObjects(res) {
    const body = res?.data;
    if (Array.isArray(body)) return body;
    return body?.data || body?.items || [];
}

/** Split filter list into RM and OP pools for form dropdowns (requires emp_id on each row). */
export function splitRmOpEmployeeLists(employees) {
    const list = Array.isArray(employees) ? employees : [];
    const activeRMs = list.filter((e) => {
        const role = String(e?.role || '').toUpperCase();
        return role === 'RM' || role === 'ADMIN';
    });
    const activeOps = list.filter((e) => String(e?.role || '').toUpperCase() === 'OP');
    return { activeRMs, activeOps };
}

/**
 * GST/customer edit forms: select value = emp_id string; keep current assignee even if not in active list.
 */
export function buildRmOpIdSelectOptions(employees, current = null) {
    const options = [];
    const seen = new Set();

    const add = (id, label) => {
        if (id == null || id === '') return;
        const value = String(id);
        if (seen.has(value)) return;
        seen.add(value);
        options.push({ value, label: label || value });
    };

    for (const emp of employees || []) {
        if (emp?.emp_id != null) {
            add(emp.emp_id, emp.username || emp.email || employeeDisplayName(emp));
        }
    }

    if (current?.id != null && current.id !== '') {
        add(current.id, current.label);
    }

    return options.sort((a, b) =>
        a.label.localeCompare(b.label, undefined, { sensitivity: 'base' })
    );
}

/**
 * RM/OP dropdown options when API returns usernames only (active-rm / active-op).
 * @param {string[]} usernames
 * @param {string|null} currentUsername - keep selected value visible if not in list
 */
export function buildRmOpUsernameSelectOptions(usernames, currentUsername = null) {
    const options = [];
    const seen = new Set();

    for (const raw of usernames || []) {
        const u = typeof raw === 'string' ? raw.trim() : String(raw?.username || '').trim();
        if (!u || seen.has(u)) continue;
        seen.add(u);
        options.push({ value: u, label: u });
    }

    const cur = typeof currentUsername === 'string'
        ? currentUsername.trim()
        : String(currentUsername?.username || currentUsername?.label || '').trim();
    if (cur && !seen.has(cur)) {
        options.push({ value: cur, label: cur });
    }

    return options.sort((a, b) =>
        a.label.localeCompare(b.label, undefined, { sensitivity: 'base' })
    );
}

/**
 * Unified builder: username lists (active-rm/op) or legacy full employee rows (emp_id).
 */
export function buildRmOpSelectOptions(pool, current = null) {
    if (!Array.isArray(pool) || pool.length === 0) {
        const curLabel = current?.label || current?.username
            || (typeof current === 'string' ? current : null);
        const curId = current?.id ?? current?.emp_id ?? null;
        if (curId != null) return buildRmOpIdSelectOptions([], { id: curId, label: curLabel });
        return curLabel ? buildRmOpUsernameSelectOptions([], curLabel) : [];
    }
    if (pool[0]?.emp_id != null) {
        return buildRmOpIdSelectOptions(pool, current);
    }
    if (typeof pool[0] === 'string' || isUsernameOnlyEntry(pool[0])) {
        const names = typeof pool[0] === 'string'
            ? pool
            : parseActiveUsernamesFromApi({ data: pool });
        const cur = current?.username || current?.label
            || (typeof current === 'string' ? current : null);
        return buildRmOpUsernameSelectOptions(names, cur);
    }
    return buildRmOpIdSelectOptions(pool, current);
}

/** Ensure &lt;select value&gt; matches option values (string emp_ids). */
export function withAssignmentFormFields(record) {
    if (!record || typeof record !== 'object') return record || {};
    const rm_id =
        record.rm_id != null && record.rm_id !== '' ? String(record.rm_id) : '';
    const created_by =
        record.created_by != null && record.created_by !== ''
            ? String(record.created_by)
            : record.op_id != null && record.op_id !== ''
              ? String(record.op_id)
              : '';
    return { ...record, rm_id, created_by, op_id: record.op_id != null ? String(record.op_id) : created_by };
}
