/** @module timer */

/**
 * Real-time timer manager for ORX dashboard runs.
 *
 * Automatically finds elements with data-started-at attribute and
 * displays elapsed time that updates every second for running runs.
 */
const RunTimer = (function () {
    /** @type {number|null} - setInterval ID for timer updates */
    let updateInterval = null;

    /** @type {Set<HTMLSpanElement>} - Set of timer elements being tracked */
    const timerElements = new Set();

    /**
     * Check if an object has the minimal shape of a timer DOM element.
     *
     * This avoids relying on `instanceof HTMLElement`, which may not be available
     * in non-browser test environments.
     *
     * @param {unknown} element - Candidate element.
     * @returns {boolean} True if element looks like a timer element.
     */
    function isTimerElement(element) {
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
     * Format duration in seconds to human-readable string.
     *
     * @param {number} totalSeconds - Total seconds to format.
     * @returns {string} Formatted duration (e.g., '2h 15m 30s', '15m 30s', '30s').
     */
    function formatDuration(totalSeconds) {
        if (totalSeconds < 0) return '-';

        const hours = Math.floor(totalSeconds / 3600);
        const minutes = Math.floor((totalSeconds % 3600) / 60);
        const seconds = Math.floor(totalSeconds % 60);

        if (hours > 0) {
            return `${hours}h ${minutes}m ${seconds}s`;
        } else if (minutes > 0) {
            return `${minutes}m ${seconds}s`;
        } else {
            return `${seconds}s`;
        }
    }

    /**
     * Update a single timer element's text content.
     *
     * @param {HTMLSpanElement} element - Timer element to update.
     * @returns {void}
     */
    function updateTimerElement(element) {
        const startedAt = element.getAttribute('data-started-at');
        const runStatus = element.getAttribute('data-run-status');

        // Never update completed/failed timers on the client; the server renders
        // a static duration based on state timestamps.
        if (runStatus !== 'running') {
            return;
        }

        if (!startedAt) {
            return;
        }

        const startDate = parseTimestamp(startedAt);
        if (!startDate) {
            element.textContent = '-';
            return;
        }

        const now = new Date();
        const elapsedSeconds = (now - startDate) / 1000;

        element.textContent = formatDuration(elapsedSeconds);
    }

    /**
     * Update all tracked timer elements.
     *
     * @returns {void}
     */
    function update() {
        timerElements.forEach((element) => {
            try {
                updateTimerElement(element);
            } catch (error) {
                console.error('Error updating timer:', error);
            }
        });
    }

    /**
     * Scan DOM for elements with data-started-at attribute and set up timers.
     *
     * @returns {void}
     */
    function scanAndInitialize() {
        const timerSelectors = [
            'span[data-timer-for][data-started-at]',
            'td[data-timer-for][data-started-at]',
            'div[data-timer-for][data-started-at]',
        ];

        timerSelectors.forEach((selector) => {
            const elements = document.querySelectorAll(selector);
            elements.forEach((element) => {
                if (
                    isTimerElement(element) &&
                    element.getAttribute('data-run-status') === 'running'
                ) {
                    timerElements.add(element);
                }
            });
        });

        // Initial update
        update();
    }

    /**
     * Initialize the timer system.
     *
     * Scans DOM for timer elements and starts update interval.
     * Safe to call multiple times - will reset interval if already running.
     *
     * @returns {void}
     */
    function initialize() {
        // Clear existing interval if any
        if (updateInterval !== null) {
            clearInterval(updateInterval);
        }

        // Clear existing elements and rescan
        timerElements.clear();
        scanAndInitialize();

        // Start update interval (every second) only if we have running timers
        if (timerElements.size > 0) {
            updateInterval = setInterval(update, 1000);
        } else {
            updateInterval = null;
        }
    }

    /**
     * Stop the timer system.
     *
     * Clears update interval and removes all tracked elements.
     *
     * @returns {void}
     */
    function shutdown() {
        if (updateInterval !== null) {
            clearInterval(updateInterval);
            updateInterval = null;
        }
        timerElements.clear();
    }

    /**
     * Manually add a timer element to track.
     *
     * @param {HTMLElement} element - Element with data-started-at attribute.
     * @returns {void}
     */
    function trackElement(element) {
        if (
            isTimerElement(element) &&
            element.getAttribute('data-run-status') === 'running'
        ) {
            timerElements.add(element);
            updateTimerElement(element);
        }
    }

    /**
     * Public API.
     */
    return {
        initialize,
        shutdown,
        update,
        trackElement,
        formatDuration,
        parseTimestamp,
    };
})();

export default RunTimer;
