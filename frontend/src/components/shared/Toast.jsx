import React, { useEffect, useState } from 'react';
import './Toast.css';

/**
 * @file Toast.jsx
 * @description A premium, minimal floating notification component.
 * Supports success and error types with smooth animations.
 */
const Toast = ({ message, type = 'success', duration = 3000, onExited }) => {
    const [isVisible, setIsVisible] = useState(false);
    const [shouldRender, setShouldRender] = useState(false);

    useEffect(() => {
        if (message) {
            setShouldRender(true);
            // Small delay for entrance animation
            const timer = setTimeout(() => setIsVisible(true), 10);

            const exitTimer = setTimeout(() => {
                setIsVisible(false);
                // Wait for exit animation before unmounting
                setTimeout(() => {
                    setShouldRender(false);
                    if (onExited) onExited();
                }, 400);
            }, duration);

            return () => {
                clearTimeout(timer);
                clearTimeout(exitTimer);
            };
        }
    }, [message, duration, onExited]);

    if (!shouldRender) return null;

    return (
        <div className={`toast-container ${isVisible ? 'visible' : ''} ${type}`}>
            <div className="toast-content">
                <div className="toast-icon">
                    {type === 'success' ? '✓' : '!'}
                </div>
                <p className="toast-message">{message}</p>
            </div>
            <div className="toast-progress" style={{ animationDuration: `${duration}ms` }} />
        </div>
    );
};

export default Toast;
