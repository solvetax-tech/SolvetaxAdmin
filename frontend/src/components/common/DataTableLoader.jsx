import React from 'react';
import { Loader2, Globe } from 'lucide-react';
import './DataTableLoader.css';

const DataTableLoader = ({ message = "Syncing Services..." }) => {
    return (
        <div className="data-table-loader">
            <div className="loader-content-v4">
                <div className="spinner-container">
                    <div className="glow-ring"></div>
                    <Loader2 size={40} className="prime-spinner" />
                    <Globe size={20} className="center-icon" />
                </div>
                <div className="loader-status-v4">
                    <span className="loader-text">{message}</span>
                    <div className="loader-progress">
                        <div className="progress-bar-shimmer"></div>
                    </div>
                </div>
            </div>
            <div className="loader-ambient">
                <div className="ambient-blob"></div>
            </div>
        </div>
    );
};

export default DataTableLoader;
