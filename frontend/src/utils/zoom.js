/**
 * Anchoring popovers under the app's global zoom.
 *
 * index.css renders the whole app at `html { zoom: 0.75 }`. That splits the
 * coordinate space in two, and mixing them is what makes a portalled popover
 * land away from its field:
 *
 *   - getBoundingClientRect() / window.innerWidth report VISUAL pixels
 *     (already multiplied by the zoom).
 *   - A `position: fixed` offset set on a descendant of the zoomed root is
 *     read in the ZOOMED space, so the browser multiplies it by the zoom
 *     again. Feeding a raw rect straight back in lands the element at
 *     rect * zoom — at 0.75 that is 25% up and to the left, 25% too narrow.
 *
 * So: convert the anchor rect and the viewport into the zoomed space once,
 * then do all placement math there, where CSS-px constants (menu widths,
 * gaps) already live. At zoom 1 every helper is an identity function.
 */

/** The zoom actually applied to <html>, read from the computed style. */
export function getAppZoom() {
    if (typeof window === 'undefined' || typeof document === 'undefined') return 1;
    const raw = window.getComputedStyle(document.documentElement).zoom;
    const zoom = parseFloat(raw);
    return Number.isFinite(zoom) && zoom > 0 ? zoom : 1;
}

/**
 * An element's rect in the space `position: fixed` offsets use.
 * Pass this to a popover's top/left/width instead of getBoundingClientRect().
 */
export function getAnchorRect(el) {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    const z = getAppZoom();
    if (z === 1) return r;
    return {
        top: r.top / z,
        right: r.right / z,
        bottom: r.bottom / z,
        left: r.left / z,
        width: r.width / z,
        height: r.height / z,
    };
}

/** Viewport size in that same space — for clamping a popover on screen. */
export function getViewportSize() {
    if (typeof window === 'undefined') return { width: 0, height: 0 };
    const z = getAppZoom();
    return { width: window.innerWidth / z, height: window.innerHeight / z };
}
