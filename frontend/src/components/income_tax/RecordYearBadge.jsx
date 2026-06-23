import React from 'react';

/** Calendar record year (mobile + year uniqueness) — distinct from ITR financial_year chips. */
export default function RecordYearBadge({ year, className = '' }) {
    if (year == null || year === '') {
        return <span className="itr-record-year-empty">-</span>;
    }
    return (
        <span
            className={`status-pill-v4 itr-record-year-pill ${className}`.trim()}
            title={`Record year ${year}`}
        >
            {year}
        </span>
    );
}
