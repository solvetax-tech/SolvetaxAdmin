import React from 'react';
import { formatSourceItem, sourceOfIncomeForDisplay } from '../../utils/incomeTaxArrays';

/** Green status-style pills for income source(s), wrapped inside the table cell. */
export default function IncomeSourcePills({ value, className = '' }) {
    const items = sourceOfIncomeForDisplay(value);
    if (!items.length) {
        return <span className="itr-source-pills-empty">-</span>;
    }

    return (
        <div className={`itr-source-pills ${className}`.trim()} role="list">
            {items.map((item, index) => (
                <span
                    key={`${String(item)}-${index}`}
                    className="status-pill-v4 status-filed itr-source-pill"
                    role="listitem"
                    title={formatSourceItem(item)}
                >
                    {formatSourceItem(item)}
                </span>
            ))}
        </div>
    );
}
