import api from '../../utils/api';
import { unwrapListPayload } from '../../utils/apiResponse';
import { formatCrmLeadDateTime } from './crmLeadTableConfig';

/** Fetch CALL activities with dial / connect timestamps. */
export async function fetchCrmLeadCallActivities(leadId, entityType, limit = 120) {
    const res = await api.get(`/api/v1/crm/leads/${leadId}/activities/calls`, {
        params: {
            limit,
            offset: 0,
            entity_type: (entityType || '').trim().toUpperCase() || undefined,
        },
    });
    return unwrapListPayload(res).items;
}

export function buildCallTimelineEvents(activities) {
    const dialed = [];
    const connected = [];

    (activities || []).forEach((act) => {
        if (act.activity_type && act.activity_type !== 'CALL') return;

        const dialedAt = act.last_dailed_at || act.performed_at;
        if (dialedAt) {
            dialed.push({
                id: `dialed-${act.id}`,
                at: dialedAt,
                act,
            });
        }
        if (act.last_connected_at) {
            connected.push({
                id: `connected-${act.id}`,
                at: act.last_connected_at,
                act,
            });
        }
    });

    const byTimeAsc = (a, b) => new Date(a.at).getTime() - new Date(b.at).getTime();
    dialed.sort(byTimeAsc);
    connected.sort(byTimeAsc);

    return { dialed, connected };
}

export function formatTimelineLabel(dateStr) {
    return formatCrmLeadDateTime(dateStr);
}

export function performerLabel(act) {
    if (act?.performed_by_first_name) return act.performed_by_first_name;
    if (act?.performed_by) return `RM ${act.performed_by}`;
    return 'RM';
}
