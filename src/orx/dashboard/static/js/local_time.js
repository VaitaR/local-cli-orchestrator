/** @module local_time */

/**
 * Local time formatter for ORX dashboard timestamps.
 *
 * Converts ISO 8601 timestamps rendered by the server into a short local-time
 * string using the viewer's machine timezone.
 */
const LocalTime = (function () {
    /** @type {Set<unknown>} - Set of DOM-like elements being tracked */
    const timeElements = new Set();

    /**
     * Check if an object has the minimal shape of a time DOM element.
     *
     * Avoids relying on `instanceof HTMLElement`, which may not be available
     * in non-browser test environments.
     *
     * @param {unknown} element - Candidate element.
     * @returns {boolean} True if element looks like a timestamp element.
     */
    function isTimeElement(element) {
        return Boolean(
            element &&
                typeof element.getAttribute === 'function' &&
                'textContent' in element
        );
    }

    /**
     * Parse ISO 8601 timestamp string to Date object.
     *
     * @param {string} isoString - ISO 8601 formatted timestamp.
     * @returns {Date|null} Parsed Date object or null if invalid.
     */
    function parseTimestamp(isoString) {
        if (!isoString) return null;
        try {
            const date = new Date(isoString);
            if (isNaN(date.getTime())) return null;
            return date;
        } catch {
            return null;
        }
    }

    /**
     * Format a Date into a short time string in the viewer's locale/timezone.
     *
     * @param {Date} date - Date to format.
     * @returns {string} Formatted time (e.g., '14:32' or '2:32 PM').
     */
    function formatShortLocalTime(date) {
        try {
            return new Intl.DateTimeFormat(undefined, {
                hour: '2-digit',
                minute: '2-digit',
            }).format(date);
        } catch {
            // Defensive fallback if Intl is unavailable.
            const hours = String(date.getHours()).padStart(2, '0');
            const minutes = String(date.getMinutes()).padStart(2, '0');
            return `${hours}:${minutes}`;
        }
    }

    /**
     * Update a single time element's text content.
     *
     * @param {unknown} element - Element to update.
     * @returns {void}
     */
    function updateTimeElement(element) {
        if (!isTimeElement(element)) return;

        const iso = element.getAttribute('data-iso');
        const date = parseTimestamp(iso);
        if (!date) {
            element.textContent = '-';
            return;
        }

        element.textContent = formatShortLocalTime(date);
    }

    /**
     * Track an element and immediately update it.
     *
     * @param {unknown} element - Element to track.
     * @returns {void}
     */
    function trackElement(element) {
        if (!isTimeElement(element)) return;
        timeElements.add(element);
        updateTimeElement(element);
    }

    /**
     * Scan DOM for elements with data-local-time and data-iso attributes.
     *
     * @param {Document|HTMLElement|unknown} root - Root node to scan.
     * @returns {void}
     */
    function initialize(root) {
        const scanRoot =
            root ||
            (typeof document !== 'undefined' && document ? document : null);
        if (!scanRoot || typeof scanRoot.querySelectorAll !== 'function') {
            return;
        }

        scanRoot.querySelectorAll('[data-local-time][data-iso]').forEach((el) => {
            trackElement(el);
        });
    }

    return {
        initialize,
        trackElement,
        parseTimestamp,
        formatShortLocalTime,
        updateTimeElement,
    };
})();

export default LocalTime;
