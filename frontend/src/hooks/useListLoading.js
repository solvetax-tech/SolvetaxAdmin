import { useRef, useCallback } from 'react';

/**
 * Only show blocking list loaders on the first fetch; later refetches keep the table visible.
 */
export function useListLoading() {
    const hasLoadedOnceRef = useRef(false);

    const wrapFetch = useCallback((setLoading, asyncFn) => {
        const showBlocking = !hasLoadedOnceRef.current;
        if (showBlocking) setLoading(true);
        return Promise.resolve(asyncFn()).finally(() => {
            hasLoadedOnceRef.current = true;
            if (showBlocking) setLoading(false);
        });
    }, []);

    return { hasLoadedOnceRef, wrapFetch };
}
