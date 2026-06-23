/**
 * Open CRM lead history: call activities only for Income Tax CRM.
 * GST (and others) still load linked registration snapshot in history view.
 */
export function openCrmLeadHistory({
    lead,
    entityType,
    setHistoryLead,
    setViewMode,
    setHistoryCurrentPage,
    setRegistrationData,
    setDetailsError,
    setDetailsLoading,
    fetchHistory,
    fetchRegistrationSnapshot,
}) {
    setHistoryLead(lead);
    setViewMode('history');
    setHistoryCurrentPage(1);
    setRegistrationData(null);
    setDetailsError(null);
    fetchHistory(lead.id, 1);

    const isIncomeTaxCrm = (entityType || '').trim().toUpperCase() === 'INCOME_TAX';
    if (isIncomeTaxCrm) {
        return;
    }

    if (typeof fetchRegistrationSnapshot === 'function') {
        fetchRegistrationSnapshot(lead);
    }
}
