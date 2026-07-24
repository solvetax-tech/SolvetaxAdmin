import React, { useState, useRef, useEffect, useCallback, useLayoutEffect } from 'react';
import { createPortal } from 'react-dom';
import { ChevronLeft, ChevronRight, Clock, Calendar as CalendarIcon, X } from 'lucide-react';
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

    // Typeable hour/minute: keep local text so the user can type freely; the
    // value is committed (clamped + emitted) on blur / Enter. This effect keeps
    // the fields in sync when the time changes from elsewhere (date pick, etc.).
    const [hourText, setHourText] = useState(String(timeParts.hour12));
    const [minuteText, setMinuteText] = useState(String(timeParts.minute).padStart(2, '0'));

    useEffect(() => {
        setHourText(String(timeParts.hour12));
        setMinuteText(String(timeParts.minute).padStart(2, '0'));
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [timeParts.hour12, timeParts.minute, timeParts.period]);

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

    const handlePeriodChange = (period) => {
        apply12HourAndEmit(getTimeBase(), timeParts.hour12, timeParts.minute, period);
    };

    const commitHour = (raw) => {
        const n = parseInt(raw, 10);
        if (Number.isNaN(n)) { setHourText(String(timeParts.hour12)); return; }
        const clamped = Math.min(12, Math.max(1, n));
        apply12HourAndEmit(getTimeBase(), clamped, timeParts.minute, timeParts.period);
    };

    const commitMinute = (raw) => {
        const n = parseInt(raw, 10);
        if (Number.isNaN(n)) { setMinuteText(String(timeParts.minute).padStart(2, '0')); return; }
        const clamped = Math.min(59, Math.max(0, n));
        apply12HourAndEmit(getTimeBase(), timeParts.hour12, clamped, timeParts.period);
    };

    const onHourInput = (e) => setHourText(e.target.value.replace(/[^0-9]/g, '').slice(0, 2));
    const onMinuteInput = (e) => setMinuteText(e.target.value.replace(/[^0-9]/g, '').slice(0, 2));

    const onHourKeyDown = (e) => {
        if (e.key === 'ArrowUp') { e.preventDefault(); commitHour(String((timeParts.hour12 % 12) + 1)); }
        else if (e.key === 'ArrowDown') { e.preventDefault(); commitHour(String(timeParts.hour12 <= 1 ? 12 : timeParts.hour12 - 1)); }
        else if (e.key === 'Enter') { e.preventDefault(); commitHour(hourText); }
    };

    const onMinuteKeyDown = (e) => {
        if (e.key === 'ArrowUp') { e.preventDefault(); commitMinute(String((timeParts.minute + 1) % 60)); }
        else if (e.key === 'ArrowDown') { e.preventDefault(); commitMinute(String((timeParts.minute + 59) % 60)); }
        else if (e.key === 'Enter') { e.preventDefault(); commitMinute(minuteText); }
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
                <div className="time-selectors time-selectors--typeable">
                    <input
                        className="time-input"
                        type="text"
                        inputMode="numeric"
                        aria-label="Hour"
                        value={hourText}
                        onChange={onHourInput}
                        onKeyDown={onHourKeyDown}
                        onBlur={() => commitHour(hourText)}
                        onFocus={(e) => e.target.select()}
                        maxLength={2}
                    />
                    <span className="time-sep">:</span>
                    <input
                        className="time-input"
                        type="text"
                        inputMode="numeric"
                        aria-label="Minute"
                        value={minuteText}
                        onChange={onMinuteInput}
                        onKeyDown={onMinuteKeyDown}
                        onBlur={() => commitMinute(minuteText)}
                        onFocus={(e) => e.target.select()}
                        maxLength={2}
                    />
                    <div className="time-period-toggle" role="group" aria-label="AM or PM">
                        <button
                            type="button"
                            className={`time-period-btn ${timeParts.period === 'AM' ? 'active' : ''}`}
                            aria-pressed={timeParts.period === 'AM'}
                            onClick={() => handlePeriodChange('AM')}
                        >
                            AM
                        </button>
                        <button
                            type="button"
                            className={`time-period-btn ${timeParts.period === 'PM' ? 'active' : ''}`}
                            aria-pressed={timeParts.period === 'PM'}
                            onClick={() => handlePeriodChange('PM')}
                        >
                            PM
                        </button>
                    </div>
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
