import React from 'react';
import {
    getCrmLeadTableColumns,
    formatCrmLeadDateTime,
    renderCrmLeadTableCell,
} from './crmLeadTableConfig';
import CrmLeadRowActions from './CrmLeadRowActions';

export default function CrmLeadsListTable({
    leads,
    loading,
    isIncomeTaxCrm,
    isGstCrm,
    isLeadPushed,
    onPush,
    pushingLeadId,
    onViewLead,
    onEditLead,
    onHistoryLead,
    emptyMessage = 'No leads found.',
    loadingMessage = 'Loading leads...',
}) {
    const columns = getCrmLeadTableColumns({ isIncomeTaxCrm });
    const colSpan = columns.length + 1;

    return (
        <table className="gst-registrations-table bordered crm-leads-table">
            <colgroup>
                {columns.map((col) => (
                    <col key={col.key} />
                ))}
                <col className="crm-col-actions" />
            </colgroup>
            <thead>
                <tr>
                    {columns.map((col) => (
                        <th key={col.key} className={col.className || ''}>
                            {col.label}
                        </th>
                    ))}
                    <th className="crm-col-sticky-details">Actions</th>
                </tr>
            </thead>
            <tbody>
                {loading ? (
                    <tr>
                        <td colSpan={colSpan} className="text-center">
                            {loadingMessage}
                        </td>
                    </tr>
                ) : leads.length === 0 ? (
                    <tr>
                        <td colSpan={colSpan} className="text-center">
                            {emptyMessage}
                        </td>
                    </tr>
                ) : (
                    leads.map((lead) => (
                        <tr key={lead.id} className="gst-reg-table-row">
                            {columns.map((col) => (
                                <td key={col.key} className={col.className || ''}>
                                    {renderCrmLeadTableCell(lead, col, formatCrmLeadDateTime)}
                                </td>
                            ))}
                            <td className="crm-col-sticky-details">
                                <CrmLeadRowActions
                                    lead={lead}
                                    isIncomeTaxCrm={isIncomeTaxCrm}
                                    isGstCrm={isGstCrm}
                                    isLeadPushed={isLeadPushed}
                                    onPush={(e) => onPush(e, lead)}
                                    pushingLeadId={pushingLeadId}
                                    onView={(e) => onViewLead(e, lead)}
                                    onEdit={(e) => onEditLead(e, lead)}
                                    onHistory={(e) => onHistoryLead(e, lead)}
                                />
                            </td>
                        </tr>
                    ))
                )}
            </tbody>
        </table>
    );
}
