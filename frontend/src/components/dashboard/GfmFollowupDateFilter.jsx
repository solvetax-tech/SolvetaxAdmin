import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Calendar, ChevronDown, ChevronLeft, ChevronRight, X } from 'lucide-react';

const toDateKey = (year, monthIndex, day) => (
    `${year}-${String(monthIndex + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`
);

const formatLocalDateStr = (dateInput) => {
    if (!dateInput) return '';
    if (typeof dateInput === 'string') {
        const trimmed = dateInput.trim();
        if (/^\d{4}-\d{2}-\d{2}$/.test(trimmed)) return trimmed;
    }
    const d = dateInput instanceof Date ? dateInput : new Date(dateInput);
    if (Number.isNaN(d.getTime())) return '';
    return toDateKey(d.getFullYear(), d.getMonth(), d.getDate());
};

export const normalizeFollowupDateList = (dates = []) => (
    [...new Set(
        (Array.isArray(dates) ? dates : [])
            .map((value) => formatLocalDateStr(value))
            .filter(Boolean),
    )].sort()
);

export const formatFollowupDateChip = (isoDate) => {
    const [year, month, day] = isoDate.split('-').map(Number);
    if (!year || !month || !day) return isoDate;
    return new Date(year, month - 1, day).toLocaleDateString('en-IN', {
        day: '2-digit',
        month: 'short',
        year: 'numeric',
    });
};

function buildCalendarDays(viewYear, viewMonth) {
    const firstDay = new Date(viewYear, viewMonth, 1).getDay();
    const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();
    const daysInPrevMonth = new Date(viewYear, viewMonth, 0).getDate();
    const cells = [];

    for (let i = firstDay - 1; i >= 0; i -= 1) {
        cells.push({ day: daysInPrevMonth - i, isCurrentMonth: false, isPastMonth: true });
    }
    for (let day = 1; day <= daysInMonth; day += 1) {
        cells.push({ day, isCurrentMonth: true });
    }
    let nextMonthDay = 1;
    while (cells.length % 7 !== 0) {
        cells.push({ day: nextMonthDay, isCurrentMonth: false, isNextMonth: true });
        nextMonthDay += 1;
    }
    return cells;
}

export default function GfmFollowupDateFilter({ value = [], onChange }) {
    const rootRef = useRef(null);
    const [open, setOpen] = useState(false);
    const [viewDate, setViewDate] = useState(() => new Date());
    const selectedDates = useMemo(() => normalizeFollowupDateList(value), [value]);

    const viewYear = viewDate.getFullYear();
    const viewMonth = viewDate.getMonth();
    const monthLabel = viewDate.toLocaleDateString('en-IN', { month: 'long', year: 'numeric' });
    const todayKey = formatLocalDateStr(new Date());
    const today = new Date();
    const isCurrentMonth = today.getFullYear() === viewYear && today.getMonth() === viewMonth;

    useEffect(() => {
        if (!open) return undefined;

        const handlePointerDown = (event) => {
            if (rootRef.current && !rootRef.current.contains(event.target)) {
                setOpen(false);
            }
        };

        document.addEventListener('mousedown', handlePointerDown);
        return () => document.removeEventListener('mousedown', handlePointerDown);
    }, [open]);

    const toggleDate = (isoDate) => {
        const next = selectedDates.includes(isoDate)
            ? selectedDates.filter((item) => item !== isoDate)
            : normalizeFollowupDateList([...selectedDates, isoDate]);
        onChange(next);
    };

    const handleDayClick = (dayObj) => {
        let year = viewYear;
        let monthIndex = viewMonth;
        let day = dayObj.day;

        if (dayObj.isPastMonth) {
            monthIndex = viewMonth - 1;
            if (monthIndex < 0) {
                monthIndex = 11;
                year = viewYear - 1;
            }
            setViewDate(new Date(year, monthIndex, 1));
        } else if (dayObj.isNextMonth) {
            monthIndex = viewMonth + 1;
            if (monthIndex > 11) {
                monthIndex = 0;
                year = viewYear + 1;
            }
            setViewDate(new Date(year, monthIndex, 1));
        }

        toggleDate(toDateKey(year, monthIndex, day));
    };

    const days = buildCalendarDays(viewYear, viewMonth);

    return (
        <div className="gfm-followup-date-filter" ref={rootRef}>
            <label className="gfm-followup-date-filter-label">Follow-up dates</label>
            <button
                type="button"
                className={`gfm-followup-date-trigger${open ? ' gfm-followup-date-trigger--open' : ''}`}
                onClick={() => setOpen((prev) => !prev)}
                aria-expanded={open}
                aria-haspopup="dialog"
            >
                <Calendar size={15} />
                <span className="gfm-followup-date-trigger-text">
                    {selectedDates.length
                        ? `${selectedDates.length} date${selectedDates.length === 1 ? '' : 's'} selected`
                        : 'Select follow-up dates'}
                </span>
                <ChevronDown size={14} className={`gfm-followup-date-trigger-caret${open ? ' is-open' : ''}`} />
            </button>

            {open && (
                <div className="gfm-followup-date-popover" role="dialog" aria-label="Select follow-up dates">
                    <div className="gfm-followup-date-popover-head">
                        <button
                            type="button"
                            className="gfm-followup-date-nav"
                            onClick={() => setViewDate(new Date(viewYear, viewMonth - 1, 1))}
                            aria-label="Previous month"
                        >
                            <ChevronLeft size={16} />
                        </button>
                        <span className="gfm-followup-date-month">{monthLabel}</span>
                        <button
                            type="button"
                            className="gfm-followup-date-nav"
                            onClick={() => setViewDate(new Date(viewYear, viewMonth + 1, 1))}
                            aria-label="Next month"
                        >
                            <ChevronRight size={16} />
                        </button>
                    </div>

                    <p className="gfm-followup-date-hint">Click days to add or remove · then Apply</p>

                    <div className="gfm-followup-date-weekdays">
                        {['S', 'M', 'T', 'W', 'T', 'F', 'S'].map((label, index) => (
                            <span key={`${label}-${index}`}>{label}</span>
                        ))}
                    </div>

                    <div className="gfm-followup-date-grid">
                        {days.map((dayObj, index) => {
                            if (!dayObj.isCurrentMonth) {
                                return <span key={`empty-${index}`} className="gfm-followup-date-day is-empty" />;
                            }

                            const dateStr = toDateKey(viewYear, viewMonth, dayObj.day);
                            const isSelected = selectedDates.includes(dateStr);
                            const isToday = isCurrentMonth && dayObj.day === today.getDate();

                            return (
                                <button
                                    key={dateStr}
                                    type="button"
                                    className={[
                                        'gfm-followup-date-day',
                                        isSelected ? 'is-selected' : '',
                                        isToday ? 'is-today' : '',
                                    ].filter(Boolean).join(' ')}
                                    onClick={() => handleDayClick(dayObj)}
                                    aria-pressed={isSelected}
                                >
                                    {dayObj.day}
                                </button>
                            );
                        })}
                    </div>

                    <div className="gfm-followup-date-popover-actions">
                        <button
                            type="button"
                            className="gfm-followup-date-quick"
                            onClick={() => toggleDate(todayKey)}
                        >
                            Today
                        </button>
                        <button
                            type="button"
                            className="gfm-followup-date-quick"
                            onClick={() => onChange([])}
                            disabled={!selectedDates.length}
                        >
                            Clear all
                        </button>
                    </div>
                </div>
            )}

            {selectedDates.length > 0 && (
                <div className="gfm-followup-date-chips" aria-label="Selected follow-up dates">
                    {selectedDates.map((isoDate) => (
                        <span key={isoDate} className="gfm-followup-date-chip">
                            {formatFollowupDateChip(isoDate)}
                            <button
                                type="button"
                                className="gfm-followup-date-chip-remove"
                                onClick={() => toggleDate(isoDate)}
                                aria-label={`Remove ${isoDate}`}
                            >
                                <X size={12} />
                            </button>
                        </span>
                    ))}
                </div>
            )}
        </div>
    );
}
