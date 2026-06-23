import React from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import './Pagination.css';

/**
 * @file Pagination.jsx
 * @description A premium, minimalistic pagination component used across all table-based views.
 * Displays as [Left Arrow] [Page Number] [Right Arrow] centered below content.
 * 
 * @param {number} currentPage - The current active page number.
 * @param {function} onPageChange - Callback function when a page arrow is clicked.
 * @param {boolean} hasMore - Whether there are more items to show (enables Next).
 * @param {boolean} loading - Whether a request is currently in progress.
 */
const Pagination = ({ currentPage, onPageChange, hasMore, loading }) => {
    return (
        <div className="premium-pagination-wrapper">
            <div className="premium-pagination">
                <button
                    className="pagination-arrow prev"
                    disabled={currentPage === 1 || loading}
                    onClick={() => onPageChange(currentPage - 1)}
                    aria-label="Previous Page"
                    title="Previous Page"
                >
                    <ChevronLeft size={18} />
                </button>

                <div className="pagination-current" title={`Current Page: ${currentPage}`}>
                    <span className="page-number">{currentPage}</span>
                </div>

                <button
                    className="pagination-arrow next"
                    disabled={!hasMore || loading}
                    onClick={() => onPageChange(currentPage + 1)}
                    aria-label="Next Page"
                    title="Next Page"
                >
                    <ChevronRight size={18} />
                </button>
            </div>
        </div>
    );
};

export default Pagination;
