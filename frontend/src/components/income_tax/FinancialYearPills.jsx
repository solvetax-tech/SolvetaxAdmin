import React from 'react';
import { asStringArray } from '../../utils/incomeTaxArrays';

/** Green status-style pills for financial year(s), wrapped inside the table cell. */
export default function FinancialYearPills({ value, className = '' }) {
    const items = asStringArray(value);
    if (!items.length) {
        return <span className="itr-source-pills-empty">-</span>;
    }

    return (
        <div className={`itr-source-pills ${className}`.trim()} role="list">
            {items.map((fy, index) => (
                <span
                    key={`${fy}-${index}`}
                    className="status-pill-v4 status-filed itr-source-pill"
                    role="listitem"
                    title={fy}
                >
                    {fy}
                </span>
            ))}
        </div>
    );
}
