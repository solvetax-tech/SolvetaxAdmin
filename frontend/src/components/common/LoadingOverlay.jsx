import React, { useState, useMemo } from 'react';

/**
 * @file LoadingOverlay.jsx
 * @description A premium fullscreen loading overlay with a randomized "line-drawing" SVG animation.
 * The icon is chosen randomly on each mount to keep the experience fresh.
 */
const LoadingOverlay = ({ message = 'Finalizing your tax details...' }) => {
    // Define a set of "Masterpiece" icons with consistent animation segments
    const icons = useMemo(() => [
        {
            name: 'Tax Document',
            viewBox: '0 0 100 120',
            paths: {
                frame: "M20 10 H70 L85 25 V110 H20 Z",
                corner: "M70 10 V25 H85",
                lines: ["M30 40 H70", "M30 55 H70", "M30 70 H55"],
                check: "M60 85 L70 95 L90 75"
            }
        },
        {
            name: 'Calculator',
            viewBox: '0 0 100 120',
            paths: {
                frame: "M25 15 H75 V105 H25 Z",
                corner: "M35 25 H65 V40 H35 Z",
                lines: ["M35 55 H45", "M55 55 H65", "M35 75 H65"],
                check: "M60 85 L70 95 L90 75"
            }
        },
        {
            name: 'Security Shield',
            viewBox: '0 0 100 120',
            paths: {
                frame: "M50 15 L20 25 V65 C20 95 50 110 50 110 C50 110 80 95 80 65 V25 Z",
                corner: "M50 35 V55",
                lines: ["M35 65 H65", "M35 75 H65", "M45 85 H55"],
                check: "M40 45 L50 55 L70 35"
            }
        },
        {
            name: 'Investment Growth',
            viewBox: '0 0 100 120',
            paths: {
                frame: "M15 100 H85 V20 H15 Z",
                corner: "M15 20 L25 10 H85 V20",
                lines: ["M25 80 L45 60", "M45 60 L65 70", "M65 70 L85 40"],
                check: "M35 40 L50 55 L80 25"
            }
        }
    ], []);

    // Select a random icon on mount
    const [activeIcon] = useState(() => icons[Math.floor(Math.random() * icons.length)]);

    const { paths, viewBox } = activeIcon;

    return (
        <div className="loading-overlay">
            <div className="loading-content-v3">
                <div className="drawing-container">
                    <svg
                        viewBox={viewBox}
                        className="drawing-svg"
                        xmlns="http://www.w3.org/2000/svg"
                    >
                        {/* The Frame (Primary Structure) */}
                        <path d={paths.frame} className="draw-path frame" />

                        {/* The Accent (Corner/Detail) */}
                        <path d={paths.corner} className="draw-path corner" />

                        {/* The Precise Details (Lines/Data) */}
                        {paths.lines.map((d, i) => (
                            <path key={i} d={d} className={`draw-path line l${i + 1}`} />
                        ))}

                        {/* The Final Check (Success/Validation) */}
                        <path d={paths.check} className="draw-path check" />
                    </svg>
                </div>
                <div className="loading-status">
                    <div className="status-dot"></div>
                    <span className="loading-text-v3">{message}</span>
                </div>
            </div>

            <div className="ambient-background">
                <div className="glow-mesh"></div>
            </div>
        </div>
    );
};

export default LoadingOverlay;
