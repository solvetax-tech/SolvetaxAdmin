import React, { useState, useRef, useEffect, useCallback, useLayoutEffect } from 'react';
import { createPortal } from 'react-dom';
import { ChevronLeft, ChevronRight, Clock, Calendar as CalendarIcon, X } from 'lucide-react';
import CustomSelect from './CustomSelect';
import { getAnchorRect, getViewportSize } from '../../utils/zoom';
import './ModernDateTimePicker.css';

function parseDateValue(value) {
    if (!value) return null;
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? null : date;
}

function toLocalInputValue(date) {
    const pad = (n) => String(n).padStart(2, '0');
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function to12HourParts(date) {
    const h24 = date.getHours();
    const period = h24 >= 12 ? 'PM' : 'AM';
    let hour12 = h24 % 12;
    if (hour12 === 0) hour12 = 12;
    return { hour12, minute: date.getMinutes(), period };
}

function apply12HourParts(baseDate, hour12, minute, period) {
    const next = new Date(baseDate);
    let h24 = parseInt(hour12, 10) % 12;
    if (period === 'PM') {
        h24 += 12;
    }
    if (period === 'AM' && parseInt(hour12, 10) === 12) {
        h24 = 0;
    }
    next.setHours(h24, parseInt(minute, 10), 0, 0);
    return next;
}

const HOUR_OPTIONS = Array.from({ length: 12 }, (_, i) => {
    const v = i + 1;
    return { value: v, label: String(v) };
});

const MINUTE_OPTIONS = Array.from({ length: 60 }, (_, i) => ({
    value: i,
    label: String(i).padStart(2, '0'),
}));

const PERIOD_OPTIONS = [
    { value: 'AM', label: 'AM' },
    { value: 'PM', label: 'PM' },
];

const ModernDateTimePicker = ({
    value,
    onChange,
    placeholder = 'Select Date & Time',
    min = null,
    className = '',
    error = false,
    outputFormat = 'iso',
    placement = 'top',
}) => {
    const [isOpen, setIsOpen] = useState(false);
    const minDate = parseDateValue(min);
    const parsedValue = parseDateValue(value);
    const [viewDate, setViewDate] = useState(parsedValue || minDate || new Date());
    const [selectedDate, setSelectedDate] = useState(parsedValue);
    const anchorRef = useRef(null);
    const popoverRef = useRef(null);
    const isCrmPicker = className.includes('modern-dt-picker--crm');
    const popoverWidth = isCrmPicker ? 320 : 280;

    useEffect(() => {
        const parsed = parseDateValue(value);
        if (parsed) {
            setSelectedDate(parsed);
            setViewDate(parsed);
        } else {
            setSelectedDate(null);
        }
    }, [value]);

    const updatePopoverPosition = useCallback(() => {
        const anchor = anchorRef.current;
        const popover = popoverRef.current;
        if (!anchor || !popover) return;

        // Anchor rect and viewport are converted out of visual pixels so they
        // share one space with offsetHeight/popoverWidth and the fixed offsets
        // written below — otherwise the app's html zoom shifts the popover.
        const rect = getAnchorRect(anchor);
        const viewport = getViewportSize();
        const popHeight = popover.offsetHeight || 400;
        const gap = 8;
        const spaceBelow = viewport.height - rect.bottom - gap;
        const spaceAbove = rect.top - gap;
        const preferBottom = placement === 'bottom';
        const openAbove = preferBottom
            ? spaceBelow < popHeight && spaceAbove > spaceBelow
            : spaceAbove >= spaceBelow || spaceBelow < popHeight;

        let top = openAbove ? rect.top - gap - popHeight : rect.bottom + gap;
        top = Math.max(8, Math.min(top, viewport.height - popHeight - 8));

        let left = isCrmPicker ? rect.right - popoverWidth : rect.left;
        left = Math.max(8, Math.min(left, viewport.width - popoverWidth - 8));

        popover.style.width = `${popoverWidth}px`;
        popover.style.top = `${top}px`;
        popover.style.left = `${left}px`;
    }, [placement, isCrmPicker, popoverWidth]);

    useLayoutEffect(() => {
        if (!isOpen) return undefined;
        updatePopoverPosition();
        const schedule = () => requestAnimationFrame(updatePopoverPosition);
        schedule();
        window.addEventListener('resize', schedule);
        window.addEventListener('scroll', schedule, true);
        return () => {
            window.removeEventListener('resize', schedule);
            window.removeEventListener('scroll', schedule, true);
        };
    }, [isOpen, updatePopoverPosition, viewDate, selectedDate]);

    useEffect(() => {
        if (!isOpen) return undefined;
        const handleClickOutside = (event) => {
            const inAnchor = anchorRef.current?.contains(event.target);
            const inPopover = popoverRef.current?.contains(event.target);
            if (!inAnchor && !inPopover) {
                setIsOpen(false);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, [isOpen]);

    const daysInMonth = (year, month) => new Date(year, month + 1, 0).getDate();
    const firstDayOfMonth = (year, month) => new Date(year, month, 1).getDay();

    const emitValue = (date) => {
        if (!date) {
            onChange('');
            return;
        }
        let next = new Date(date);
        if (minDate && next < minDate) {
            next = new Date(minDate);
        }
        setSelectedDate(next);
        onChange(outputFormat === 'local' ? toLocalInputValue(next) : next.toISOString());
    };

    const getTimeBase = () => selectedDate || minDate || new Date();
    const timeParts = to12HourParts(getTimeBase());

    const handlePrevMonth = () => {
        setViewDate(new Date(viewDate.getFullYear(), viewDate.getMonth() - 1, 1));
    };

    const handleNextMonth = () => {
        setViewDate(new Date(viewDate.getFullYear(), viewDate.getMonth() + 1, 1));
    };

    const handleDateSelect = (day) => {
        const newDate = new Date(viewDate.getFullYear(), viewDate.getMonth(), day);
        const ref = selectedDate || minDate || (() => {
            const d = new Date();
            d.setHours(10, 0, 0, 0);
            return d;
        })();
        const parts = to12HourParts(ref);
        apply12HourAndEmit(newDate, parts.hour12, parts.minute, parts.period);
    };

    const apply12HourAndEmit = (baseDate, hour12, minute, period) => {
        emitValue(apply12HourParts(baseDate, hour12, minute, period));
    };

    const handleHour12Change = (hour12) => {
        apply12HourAndEmit(getTimeBase(), hour12, timeParts.minute, timeParts.period);
    };

    const handleMinuteChange = (minute) => {
        apply12HourAndEmit(getTimeBase(), timeParts.hour12, minute, timeParts.period);
    };

    const handlePeriodChange = (period) => {
        apply12HourAndEmit(getTimeBase(), timeParts.hour12, timeParts.minute, period);
    };

    const isDayDisabled = (day) => {
        if (!minDate) return false;
        const candidate = new Date(viewDate.getFullYear(), viewDate.getMonth(), day, 23, 59, 59, 999);
        return candidate < new Date(minDate.getFullYear(), minDate.getMonth(), minDate.getDate());
    };

    const isSameCalendarDay = (day, date) => date
        && day === date.getDate()
        && viewDate.getMonth() === date.getMonth()
        && viewDate.getFullYear() === date.getFullYear();

    const isToday = (day) => {
        const today = new Date();
        if (!isSameCalendarDay(day, today)) return false;
        // Only highlight today when nothing is picked, or today is the picked date
        if (!selectedDate) return true;
        return isSameCalendarDay(day, selectedDate);
    };

    const isSelected = (day) => isSameCalendarDay(day, selectedDate);

    const monthNames = [
        'January', 'February', 'March', 'April', 'May', 'June',
        'July', 'August', 'September', 'October', 'November', 'December',
    ];

    const generateDays = () => {
        const days = [];
        const totalDays = daysInMonth(viewDate.getFullYear(), viewDate.getMonth());
        const startDay = firstDayOfMonth(viewDate.getFullYear(), viewDate.getMonth());

        for (let i = 0; i < startDay; i += 1) {
            days.push(<div key={`empty-${i}`} className="calendar-day empty" />);
        }

        for (let d = 1; d <= totalDays; d += 1) {
            const disabled = isDayDisabled(d);
            days.push(
                <button
                    type="button"
                    key={d}
                    className={`calendar-day ${isSelected(d) ? 'selected' : ''} ${isToday(d) ? 'today' : ''} ${disabled ? 'disabled' : ''}`}
                    onClick={() => !disabled && handleDateSelect(d)}
                    disabled={disabled}
                >
                    {d}
                </button>
            );
        }
        return days;
    };

    const formatDisplay = (date) => {
        if (!date) return '';
        return date.toLocaleString('en-IN', {
            day: '2-digit',
            month: 'short',
            year: 'numeric',
            hour: 'numeric',
            minute: '2-digit',
            hour12: true,
        });
    };

    const handleClear = (e) => {
        e?.stopPropagation?.();
        setSelectedDate(null);
        onChange('');
    };

    const handleToday = () => {
        const now = new Date();
        emitValue(now);
        setViewDate(now);
    };

    const handleDone = () => {
        if (!selectedDate && minDate) {
            emitValue(minDate);
            setViewDate(minDate);
        }
        setIsOpen(false);
    };

    const rootClass = [
        'modern-dt-picker',
        className,
        placement === 'bottom' ? 'modern-dt-picker--placement-bottom' : '',
        error ? 'modern-dt-picker--error' : '',
    ].filter(Boolean).join(' ');

    const popoverContent = isOpen ? (
        <div
            className="dt-popover dt-popover--portal"
            ref={popoverRef}
            onClick={(e) => e.stopPropagation()}
            onMouseDown={(e) => e.stopPropagation()}
        >
            <div className="calendar-section">
                <div className="calendar-header">
                    <button type="button" onClick={handlePrevMonth} className="nav-btn"><ChevronLeft size={16} /></button>
                    <span>{monthNames[viewDate.getMonth()]} {viewDate.getFullYear()}</span>
                    <button type="button" onClick={handleNextMonth} className="nav-btn"><ChevronRight size={16} /></button>
                </div>
                <div className="calendar-weekdays">
                    {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map((d) => <span key={d}>{d[0]}</span>)}
                </div>
                <div className="calendar-grid">
                    {generateDays()}
                </div>
            </div>

            <div className="time-section">
                <div className="time-header">
                    <Clock size={14} />
                    <span>Set Time (12-hour)</span>
                </div>
                <div className="time-selectors time-selectors--12h">
                    <CustomSelect
                        className="custom-select--compact"
                        value={timeParts.hour12}
                        options={HOUR_OPTIONS}
                        onChange={handleHour12Change}
                        ariaLabel="Hour"
                        menuMaxHeight={160}
                    />
                    <span className="time-sep">:</span>
                    <CustomSelect
                        className="custom-select--compact"
                        value={timeParts.minute}
                        options={MINUTE_OPTIONS}
                        onChange={handleMinuteChange}
                        ariaLabel="Minute"
                        menuMaxHeight={160}
                    />
                    <CustomSelect
                        className="custom-select--compact"
                        value={timeParts.period}
                        options={PERIOD_OPTIONS}
                        onChange={handlePeriodChange}
                        ariaLabel="AM or PM"
                        menuMaxHeight={96}
                    />
                </div>
            </div>

            <div className="dt-popover-footer">
                <button type="button" className="dt-footer-btn dt-footer-btn--clear" onClick={handleClear}>
                    Clear
                </button>
                <button type="button" className="dt-footer-btn dt-footer-btn--today" onClick={handleToday}>
                    Today
                </button>
                <button type="button" className="dt-footer-btn dt-footer-btn--done" onClick={handleDone}>
                    Done
                </button>
            </div>
        </div>
    ) : null;

    return (
        <div className={rootClass} ref={anchorRef}>
            <div
                className={`dt-input ${isOpen ? 'active' : ''}`}
                onClick={() => setIsOpen((open) => !open)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        setIsOpen((open) => !open);
                    }
                }}
            >
                <CalendarIcon size={16} className="dt-icon" />
                <span className={`dt-value ${!selectedDate ? 'placeholder' : ''}`}>
                    {selectedDate ? formatDisplay(selectedDate) : placeholder}
                </span>
                {selectedDate && (
                    <X
                        size={18}
                        className="dt-clear"
                        onClick={handleClear}
                    />
                )}
            </div>

            {typeof document !== 'undefined' && popoverContent
                ? createPortal(popoverContent, document.body)
                : null}
        </div>
    );
};

export default ModernDateTimePicker;
