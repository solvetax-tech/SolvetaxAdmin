import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { Bell, Clock, Info, UserPlus, FileText, Settings, Trash2, ArrowRight } from 'lucide-react';
import './NotificationsTab.css';
import { clearNotifications } from '../../utils/notificationUtils';
import { dispatchGstFilingFocusOpen, resolveGstFocusFromAction } from '../../utils/dashboardApi';

const NotificationsTab = () => {
    const navigate = useNavigate();
    const [notifications, setNotifications] = useState([]);
    const [loading, setLoading] = useState(true);

    const fetchNotifications = useCallback(() => {
        try {
            const localNotifs = JSON.parse(localStorage.getItem('st_notifications') || '[]');
            // Filter out CRM notifications to keep main system feed clean
            const filtered = localNotifs.filter(n => n.context !== 'CRM');
            setNotifications(filtered);
        } catch (err) {
            console.error('Notifications fetch failed:', err);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchNotifications();

        // Listen for internal updates
        window.addEventListener('st_notifications_updated', fetchNotifications);

        return () => {
            window.removeEventListener('st_notifications_updated', fetchNotifications);
        };
    }, [fetchNotifications]);

    // PRE-PROCESS: Identify all task IDs that are marked as COMPLETED in the current feed
    const completedTaskIds = useMemo(() => {
        return notifications.reduce((acc, item) => {
            const title = String(item.title || '').toLowerCase();
            const desc = String(item.description || '').toLowerCase();

            // If the notification itself is about completion
            if (title.includes('completed') || desc.includes('completed')) {
                // Try to get ID from explicit action first
                const actionId = item.action?.path?.match(/complete_task_id=(\d+)/)?.[1];
                if (actionId) {
                    acc.add(actionId);
                } else {
                    // Fallback to regex on description (e.g. #123)
                    const idMatch = desc.match(/#(\d+)/);
                    if (idMatch) acc.add(idMatch[1]);
                }
            }
            return acc;
        }, new Set());
    }, [notifications]);

    const handleClearAll = () => {
        if (notifications.length === 0) return;

        const cards = document.querySelectorAll('.nt-card');
        cards.forEach((card, i) => {
            setTimeout(() => {
                card.classList.add('clearing');
            }, i * 50);
        });

        setTimeout(() => {
            clearNotifications();
        }, cards.length * 50 + 300);
    };

    const handleActionClick = (action) => {
        if (!action || !action.path) return;

        // --- Hybrid Redirection: Broadcast Signal ---
        // If the path contains complete_task_id, send a global signal so the Followups component
        // can handle it instantly even if it's already mounted on the same tab.
        const taskIdMatch = action.path.match(/complete_task_id=(\d+)/);
        const categoryMatch = action.path.match(/[?&]category=(payments|services)/);
        if (taskIdMatch && taskIdMatch[1]) {
            window.dispatchEvent(new CustomEvent('st_open_followup', {
                detail: {
                    taskId: taskIdMatch[1],
                    category: categoryMatch?.[1] || 'services',
                },
            }));
        }

        const gstFocus = resolveGstFocusFromAction(action);
        if (gstFocus) {
            dispatchGstFilingFocusOpen(gstFocus);
        }

        // Use navigate to change routes/tabs
        navigate(action.path);

        // Dispatch a global event to close any overlays (like the sidebar or notification drawer)
        window.dispatchEvent(new Event('st_close_drawers'));
    };

    const getIcon = (type) => {
        switch (type) {
            case 'CREATE': return <UserPlus size={14} className="nt-icon create" />;
            case 'UPDATE': return <FileText size={18} className="nt-icon update" />;
            case 'SYSTEM': return <Settings size={18} className="nt-icon system" />;
            default: return <Info size={18} className="nt-icon info" />;
        }
    };

    const getNotificationAction = (item) => {
        // 1. Return explicitly stored action if present
        if (item.action) return item.action;

        // 2. Infer action for legacy notifications (backward compatibility)
        const title = String(item.title || '').toLowerCase();
        const desc = String(item.description || '').toLowerCase();

        // Check for Task ID in description (matches #123)
        const idMatch = desc.match(/#(\d+)/);
        const taskId = idMatch ? idMatch[1] : null;

        if (title.includes('gst filing follow-up')) {
            return {
                label: 'Open GST Filings',
                path: '/dashboard?tab=dashboard&sub=gst-filing-matrix',
            };
        }

        // Follow-up related inference
        if (title.includes('follow-up')) {
            // Upcoming or Scheduled
            if (title.includes('upcoming') || title.includes('scheduled')) {
                return {
                    label: 'Complete Now',
                    path: `/dashboard?tab=dashboard&sub=followups${taskId ? `&complete_task_id=${taskId}` : ''}`
                };
            }

            // Missed or Overdue
            if (title.includes('missed') || title.includes('overdue')) {
                return {
                    label: 'Complete / Reschedule',
                    path: `/dashboard?tab=dashboard&sub=followups${taskId ? `&complete_task_id=${taskId}` : ''}`
                };
            }

            // Completed
            if (title.includes('completed') || title.includes('finished')) {
                return {
                    label: 'View History',
                    path: `/dashboard?tab=dashboard&sub=followups${taskId ? `&complete_task_id=${taskId}` : ''}`
                };
            }

            return {
                label: 'View in Dashboard',
                path: '/dashboard?tab=dashboard&sub=followups'
            };
        }

        // Customer related inference
        if (title.includes('customer') && title.includes('created')) {
            return {
                label: 'View Customers',
                path: '/dashboard?tab=customers'
            };
        }

        return null;
    };

    const formatTime = (ts) => {
        const date = new Date(ts);
        return date.toLocaleString('en-IN', {
            day: 'numeric',
            month: 'short',
            hour: '2-digit',
            minute: '2-digit'
        });
    };

    return (
        <div className="notifications-tab-container">
            <div className="nt-header">
                <div className="nt-header-main">
                    <div className="nt-header-title">
                        <Bell className="nt-bell" />
                        <h1>Activity Feed</h1>
                    </div>
                    <p>Real-time updates on system changes and employee actions.</p>
                </div>
                {notifications.length > 0 && (
                    <button className="nt-clear-btn" onClick={handleClearAll} title="Clear all notifications">
                        <Trash2 size={16} />
                        Clear All
                    </button>
                )}
            </div>

            <div className="nt-content">
                {loading ? (
                    <div className="nt-loading">Loading activity...</div>
                ) : notifications.length === 0 ? (
                    <div className="nt-empty">No notifications yet.</div>
                ) : (
                    <div className="nt-list">
                        {notifications.map((item) => {
                            const action = getNotificationAction(item);

                            // Check if this specific item is ALREADY completed based on the overall feed
                            const pathTaskId = action?.path?.match(/complete_task_id=(\d+)/)?.[1];
                            const safeDesc = String(item.description || '');
                            const descTaskId = safeDesc.match(/#(\d+)/)?.[1];
                            const currentTaskId = pathTaskId || descTaskId;

                            const isAlreadyDone = currentTaskId && completedTaskIds.has(currentTaskId) && action?.label === 'Complete Now';

                            return (
                                <div key={item.id} className="nt-card">
                                    <div className="nt-card-icon-wrapper">
                                        {getIcon(item.type)}
                                    </div>
                                    <div className="nt-card-main">
                                        <h3 className="nt-card-title">{item.title}</h3>
                                        <p className="nt-description">{item.description}</p>
                                    </div>
                                    <div className="nt-card-right">
                                        <div className="nt-timestamp">
                                            <Clock size={12} />
                                            <span>{formatTime(item.timestamp)}</span>
                                        </div>
                                        {action && (
                                            <button
                                                className={`nt-action-btn-v2 ${isAlreadyDone ? 'disabled' : ''}`}
                                                onClick={() => !isAlreadyDone && handleActionClick(action)}
                                                disabled={isAlreadyDone}
                                                style={{ cursor: isAlreadyDone ? 'not-allowed' : 'pointer' }}
                                            >
                                                {isAlreadyDone ? 'Already Done' : (action.label || 'View Action')}
                                                {!isAlreadyDone && <ArrowRight size={14} />}
                                            </button>
                                        )}
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                )}
            </div>
        </div>
    );
};

export default NotificationsTab;