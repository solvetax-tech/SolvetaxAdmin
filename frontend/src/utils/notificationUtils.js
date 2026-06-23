/**
 * Utility for managing local notifications stored in localStorage.
 */

export const addNotification = (title, description, type = 'INFO', action = null, context = 'MAIN') => {
    try {
        const newNotif = {
            id: Date.now(),
            title,
            description,
            type, // 'CREATE', 'UPDATE', 'INFO', 'SYSTEM'
            action, // { label, path }
            context, // 'MAIN', 'CRM'
            timestamp: new Date().toISOString(),
        };

        const existing = JSON.parse(localStorage.getItem('st_notifications') || '[]');
        localStorage.setItem('st_notifications', JSON.stringify([newNotif, ...existing]));

        // Dispatch a custom event so other components can listen for updates
        window.dispatchEvent(new Event('st_notifications_updated'));

        return newNotif;
    } catch (err) {
        console.error('Failed to add notification:', err);
        return null;
    }
};

export const clearNotifications = () => {
    try {
        localStorage.removeItem('st_notifications');
        window.dispatchEvent(new Event('st_notifications_updated'));
        return true;
    } catch (err) {
        console.error('Failed to clear notifications:', err);
        return false;
    }
};
