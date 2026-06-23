import React, { useEffect, useState } from 'react';
import { CheckCircle, XCircle, Info, X } from 'lucide-react';
import './Toast.css';

const Toast = ({ message, type = 'success', onClose, duration = 3000 }) => {
    const [isExiting, setIsExiting] = useState(false);

    useEffect(() => {
        if (!message) return;

        const timer = setTimeout(() => {
            handleClose();
        }, duration);

        return () => clearTimeout(timer);
    }, [message, duration]);

    const handleClose = () => {
        setIsExiting(true);
        // Wait for exit animation to finish before unmounting
        setTimeout(() => {
            onClose();
            setIsExiting(false);
        }, 400); // Matches CSS animation duration
    };

    if (!message) return null;

    const icons = {
        success: <CheckCircle className="toast-icon success" size={20} />,
        error: <XCircle className="toast-icon error" size={20} />,
        info: <Info className="toast-icon info" size={20} />,
    };

    return (
        <div className={`toast-container-glass ${type} ${isExiting ? 'exiting' : ''}`}>
            <div className="toast-content">
                {icons[type]}
                <span className="toast-message">{message}</span>
                <button className="toast-close-btn" onClick={handleClose}>
                    <X size={14} />
                </button>
            </div>
            <div className="toast-progress-bar" style={{ animationDuration: `${duration}ms` }} />
        </div>
    );
};

export default Toast;
