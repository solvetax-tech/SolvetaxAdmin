import React from 'react';
import { useNavigate } from 'react-router-dom';
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
    const navigate = useNavigate();

    // Entity ID links to the linked record over in the main system (the GST
    // registration or ITR this lead was pushed to).
    const openEntityInMainSystem = (lead) => {
        const eid = lead.entity_id;
        if (eid == null || eid === '') return;
        if (isIncomeTaxCrm) {
            navigate('/dashboard?tab=income-tax');
        } else {
            navigate(`/dashboard?tab=gst&sub=registrations&gst_registration_id=${encodeURIComponent(eid)}`);
        }
    };

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
                                    {col.key === 'id' ? (
                                        <button type="button" className="row-id-link" title="View lead" onClick={(e) => onViewLead(e, lead)}>{lead.id ?? '-'}</button>
                                    ) : col.key === 'entity_id' ? (
                                        (lead.entity_id != null && lead.entity_id !== '') ? (
                                            <button
                                                type="button"
                                                className="row-id-link"
                                                title="Open this record in the main system"
                                                onClick={(e) => { e.stopPropagation(); openEntityInMainSystem(lead); }}
                                            >
                                                {lead.entity_id}
                                            </button>
                                        ) : '-'
                                    ) : (
                                        renderCrmLeadTableCell(lead, col, formatCrmLeadDateTime)
                                    )}
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
