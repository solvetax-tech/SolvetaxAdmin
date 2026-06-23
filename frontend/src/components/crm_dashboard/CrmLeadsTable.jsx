import React from 'react';
import { CRM_LEAD_TABLE_COLUMNS, renderLeadTableCell } from './crmLeadTableConfig';
import './crmLeadsBoard.css';

const CrmLeadsTable = ({
    leads,
    loading,
    emptyMessage = 'No leads found.',
    loadingMessage = 'Loading leads...',
    onRowClick,
    onDetailsClick,
    formatDateTime,
}) => {
    const colSpan = CRM_LEAD_TABLE_COLUMNS.length + 1;

    return (
        <table className="gst-registrations-table bordered crm-leads-table">
            <thead>
                <tr>
                    {CRM_LEAD_TABLE_COLUMNS.map((col) => (
                        <th key={col.key} className={col.className || ''}>
                            {col.label}
                        </th>
                    ))}
                    <th className="crm-col-sticky-details">Details</th>
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
                        <tr
                            key={lead.id}
                            className="gst-reg-table-row clickable"
                            onClick={() => onRowClick?.(lead)}
                        >
                            {CRM_LEAD_TABLE_COLUMNS.map((col) => (
                                <td key={col.key} className={col.className || ''}>
                                    {renderLeadTableCell(lead, col, { formatDateTime })}
                                </td>
                            ))}
                            <td className="crm-col-sticky-details">
                                <button
                                    type="button"
                                    className="btn-history-mini"
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        onDetailsClick?.(lead);
                                    }}
                                    title="View full lead details"
                                >
                                    Details
                                </button>
                            </td>
                        </tr>
                    ))
                )}
            </tbody>
        </table>
    );
};

export default CrmLeadsTable;
