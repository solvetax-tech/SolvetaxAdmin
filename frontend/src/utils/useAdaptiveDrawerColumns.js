import { useLayoutEffect } from 'react';

/**
 * Adaptive-width side-drawer columns.
 *
 * Records vary in how much they hold: some drawers are one screenful, some are
 * three. Instead of a fixed half-screen panel that scrolls top-to-bottom, this
 * measures the body's true stacked height and tags the panel with `data-cols` =
 * the fewest CSS columns that keep the content within one screenful. CSS then
 * flows the body into that many balanced columns and widens the panel to fit
 * (little data -> narrow, more data -> wider, capped by the CSS max-width at
 * "just past the middle" of the screen).
 *
 * Why measure in JS: pure CSS intrinsic sizing can't turn "lots of vertical
 * content" into "a wider box" — only a measurement can. It stays zoom-safe (the
 * app runs under html { zoom: 0.75 }) because JS only ever reads a height RATIO
 * (scrollHeight / clientHeight, both scaled equally) and outputs an integer;
 * every actual width lives in CSS.
 *
 * The paired CSS must render a SINGLE column when data-cols="1" so the initial
 * measurement reads the true stacked height.
 *
 * @param panelRef  ref to the drawer panel element (receives data-cols)
 * @param bodyRef   ref to the scrollable body element
 * @param opts.enabled  when false, clears data-cols (drawer keeps its default width)
 * @param opts.maxCols  hard cap on columns (default 3)
 * @param deps      re-measure when these change (open, data, edit mode, ...)
 */
export default function useAdaptiveDrawerColumns(
    panelRef,
    bodyRef,
    { enabled = true, maxCols = 3 } = {},
    deps = [],
) {
    useLayoutEffect(() => {
        const panel = panelRef.current;
        const body = bodyRef.current;
        if (!panel) return undefined;
        if (!enabled || !body) {
            delete panel.dataset.cols;
            return undefined;
        }

        const measure = () => {
            // Force a single column to read the true stacked content height,
            // then pick the fewest columns that keep it within one screenful.
            panel.dataset.cols = '1';
            const avail = body.clientHeight;
            const total = body.scrollHeight;
            if (avail <= 0) return;
            const cols = Math.min(maxCols, Math.max(1, Math.ceil(total / avail)));
            panel.dataset.cols = String(cols);
        };

        // Measure after layout + fonts settle (two frames), then on resize.
        const raf = requestAnimationFrame(() => requestAnimationFrame(measure));
        window.addEventListener('resize', measure);
        return () => {
            cancelAnimationFrame(raf);
            window.removeEventListener('resize', measure);
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, deps);
}
