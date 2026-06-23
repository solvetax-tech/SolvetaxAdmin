import React, { useState } from 'react';
import { Users, ChevronRight, Settings as SettingsIcon } from 'lucide-react';
import Version from '../versions/Version';
import { History } from 'lucide-react';
import CustomerServiceBulkAssign from '../customers/CustomerServiceBulkAssign';
import './SettingsTab.css';

const SettingsTab = ({ isAdmin, setToastMessage }) => {
    const [currentView, setCurrentView] = useState('hub');
    const [loading, setLoading] = useState(true);

    React.useEffect(() => {
        const timer = setTimeout(() => setLoading(false), 800);
        return () => clearTimeout(timer);
    }, []);

    const settingsOptions = [
        {
            id: 'bulk-assign',
            title: 'Bulk Assign',
            description: 'Assign RM or OP to pending customer services in bulk.',
            icon: <Users size={24} className="option-icon" />,
            allowed: isAdmin,
            action: () => setCurrentView('bulk-assign'),
        },
        {
            id: 'versions',
            title: 'System Audit',
            description: 'Track changes, version history, and system-wide audit logs.',
            icon: <History size={24} className="option-icon" />,
            allowed: isAdmin,
            action: () => setCurrentView('versions'),
        },
    ];

    if (loading && currentView === 'hub') {
        return (
            <div className="settings-hub-container">
                <div className="skeleton-hub-header">
                    <div className="skeleton-title" />
                    <div className="skeleton-subtitle" />
                </div>

                <div className="settings-options-grid">
                    {[...Array(2)].map((_, i) => (
                        <div key={i} className="skeleton-card">
                            <div className="skeleton-icon" />
                            <div className="skeleton-info">
                                <div className="skeleton-text-h" />
                                <div className="skeleton-text-p" />
                            </div>
                        </div>
                    ))}
                </div>
            </div>
        );
    }

    if (currentView === 'bulk-assign') {
        return (
            <div className="settings-page-wrapper">
                <div className="settings-breadcrumb">
                    <button onClick={() => setCurrentView('hub')} className="breadcrumb-link">
                        <SettingsIcon size={14} /> Settings
                    </button>
                    <ChevronRight size={14} className="breadcrumb-separator" />
                    <span className="breadcrumb-current">Bulk Assign</span>
                </div>
                <CustomerServiceBulkAssign setToastMessage={setToastMessage} />
            </div>
        );
    }

    if (currentView === 'versions') {
        const auditBreadcrumb = (
            <div className="settings-breadcrumb settings-breadcrumb--inline">
                <button type="button" onClick={() => setCurrentView('hub')} className="breadcrumb-link">
                    <SettingsIcon size={14} /> Settings
                </button>
                <ChevronRight size={14} className="breadcrumb-separator" />
                <span className="breadcrumb-current">System Audit Log</span>
            </div>
        );

        return (
            <div className="settings-page-wrapper settings-page-wrapper--audit">
                <Version isAdmin={isAdmin} headerStart={auditBreadcrumb} />
            </div>
        );
    }

    return (
        <div className="settings-hub-container">
            <div className="settings-hub-header">
                <div className="header-accent-line" />
                <h1>System Settings</h1>
                <p>Manage customer service assignments, portal configurations, and system permissions.</p>
            </div>

            <div className="settings-options-grid">
                {settingsOptions.map(option => (
                    option.allowed && (
                        <div key={option.id} className="settings-option-card" onClick={option.action}>
                            <div className="option-icon-wrapper">
                                {option.icon}
                            </div>
                            <div className="option-content">
                                <h3>{option.title}</h3>
                                <p>{option.description}</p>
                            </div>
                            <div className="option-arrow">
                                <ChevronRight size={20} />
                            </div>
                        </div>
                    )
                ))}
            </div>
        </div>
    );
};

export default SettingsTab;
