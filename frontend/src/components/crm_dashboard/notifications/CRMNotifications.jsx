import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { Bell, Clock, Info, UserPlus, FileText, Settings, Trash2, ArrowRight } from 'lucide-react';
import './CRMNotifications.css';
import { clearNotifications } from '../../../utils/notificationUtils';

const CRMNotifications = () => {
    const navigate = useNavigate();
    const [notifications, setNotifications] = useState([]);
    const [loading, setLoading] = useState(true);

    const fetchNotifications = useCallback(() => {
        try {
            // Using the isolated CRM key
            const localNotifs = JSON.parse(localStorage.getItem('st_crm_notifications') || '[]');
            setNotifications(localNotifs);
        } catch (err) {
            console.error('Notifications fetch failed:', err);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchNotifications();

        // Listen for CRM-specific updates
        window.addEventListener('st_crm_notifications_updated', fetchNotifications);

        return () => {
            window.removeEventListener('st_crm_notifications_updated', fetchNotifications);
        };
    }, [fetchNotifications]);

    // PRE-PROCESS: Identify all task IDs that are marked as COMPLETED in the current feed
    const completedTaskIds = useMemo(() => {
        return notifications.reduce((acc, item) => {
            const title = String(item.title || '').toLowerCase();
            const desc = String(item.description || '').toLowerCase();
            
            if (title.includes('completed') || desc.includes('completed')) {
                const actionId = item.action?.path?.match(/complete_task_id=(\d+)/)?.[1];
                if (actionId) {
                    acc.add(actionId);
                } else {
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
            try {
                localStorage.removeItem('st_crm_notifications');
                window.dispatchEvent(new Event('st_crm_notifications_updated'));
            } catch (err) {
                console.error('Failed to clear CRM notifications:', err);
            }
        }, cards.length * 50 + 300);
    };

    const handleActionClick = (action) => {
        if (!action || !action.path) return;
        
        // --- Redirection Logic for CRM ---
        const leadIdMatch = action.path.match(/target_lead_id=(\d+)/);
        const viewMatch = action.path.match(/target_view=([^&]+)/);
        
        if (leadIdMatch && leadIdMatch[1]) {
            console.log(`[CRMNotifications] Redirecting to Lead: ${leadIdMatch[1]}. View: ${viewMatch?.[1]}`);
            window.dispatchEvent(new CustomEvent('st_open_crm_lead', { 
                detail: { 
                    leadId: leadIdMatch[1],
                    view: viewMatch ? viewMatch[1] : null 
                } 
            }));
        }

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

        // Use navigate to change routes/tabs
        navigate(action.path);
        
        // Dispatch a global event to close any overlays (like the sidebar or notification drawer)
        window.dispatchEvent(new Event('st_close_drawers'));
    };

    const getIcon = (type) => {
        switch (type) {
            case 'CREATE': return <UserPlus size={18} className="nt-icon create" />;
            case 'UPDATE': return <FileText size={18} className="nt-icon update" />;
            case 'SYSTEM': return <Settings size={18} className="nt-icon system" />;
            default: return <Info size={18} className="nt-icon info" />;
        }
    };

    const getNotificationAction = (item) => {
        if (item.action) return item.action;

        const title = String(item.title || '').toLowerCase();
        const desc = String(item.description || '').toLowerCase();
        const idMatch = desc.match(/#(\d+)/);
        const taskId = idMatch ? idMatch[1] : null;

        if (title.includes('follow-up')) {
            if (title.includes('upcoming') || title.includes('scheduled')) {
                return {
                    label: 'Complete Now',
                    path: `/dashboard?tab=dashboard&sub=followups${taskId ? `&complete_task_id=${taskId}` : ''}`
                };
            }
            if (title.includes('missed') || title.includes('overdue')) {
                return { label: 'Complete / Reschedule', path: `/dashboard?tab=dashboard&sub=followups${taskId ? `&complete_task_id=${taskId}` : ''}` };
            }
            if (title.includes('completed')) {
                return { label: 'View History', path: `/dashboard?tab=dashboard&sub=followups${taskId ? `&complete_task_id=${taskId}` : ''}` };
            }
            return { label: 'View in Dashboard', path: '/dashboard?tab=dashboard&sub=followups' };
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
                        <h1>CRM Activity Feed</h1>
                    </div>
                    <p>Track your leads and follow-ups in real-time.</p>
                </div>
                {notifications.length > 0 && (
                    <button className="nt-clear-btn" onClick={handleClearAll}>
                        <Trash2 size={16} /> Clear All
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
                                            <Clock size={12} /> <span>{formatTime(item.timestamp)}</span>
                                        </div>
                                        {action && (
                                            <button 
                                                className={`nt-action-btn-v2 ${isAlreadyDone ? 'disabled' : ''}`}
                                                onClick={() => !isAlreadyDone && handleActionClick(action)}
                                                disabled={isAlreadyDone}
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

export default CRMNotifications;
