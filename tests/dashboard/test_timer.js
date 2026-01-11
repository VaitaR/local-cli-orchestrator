/**
 * Jest-style test suite for RunTimer module.
 *
 * Tests duration formatting, timestamp parsing, and edge cases.
 * @module test_timer
 */

import RunTimer from '../../src/orx/dashboard/static/js/timer.js';

describe('RunTimer', () => {
    describe('formatDuration', () => {
        it('should format seconds only duration (e.g., 45s)', () => {
            expect(RunTimer.formatDuration(45)).toBe('45s');
            expect(RunTimer.formatDuration(30)).toBe('30s');
            expect(RunTimer.formatDuration(59)).toBe('59s');
        });

        it('should format minutes and seconds (e.g., 2m 5s)', () => {
            expect(RunTimer.formatDuration(125)).toBe('2m 5s');
            expect(RunTimer.formatDuration(65)).toBe('1m 5s');
            expect(RunTimer.formatDuration(359)).toBe('5m 59s');
        });

        it('should format hours, minutes, and seconds (e.g., 1h 1m 1s)', () => {
            expect(RunTimer.formatDuration(3661)).toBe('1h 1m 1s');
            expect(RunTimer.formatDuration(7325)).toBe('2h 2m 5s');
            expect(RunTimer.formatDuration(3600)).toBe('1h 0m 0s');
        });

        it('should handle zero duration (0s)', () => {
            expect(RunTimer.formatDuration(0)).toBe('0s');
        });

        it('should handle negative duration', () => {
            expect(RunTimer.formatDuration(-1)).toBe('-');
            expect(RunTimer.formatDuration(-100)).toBe('-');
        });

        it('should handle large durations', () => {
            expect(RunTimer.formatDuration(86400)).toBe('24h 0m 0s');
            expect(RunTimer.formatDuration(90061)).toBe('25h 1m 1s');
        });
    });

    describe('parseTimestamp', () => {
        it('should correctly parse ISO 8601 timestamps', () => {
            const timestamp = '2025-01-11T12:00:00Z';
            const result = RunTimer.parseTimestamp(timestamp);

            expect(result).toBeInstanceOf(Date);
            expect(result).not.toBeNull();
            expect(result.getTime()).not.toBeNaN();
        });

        it('should handle timezone offsets', () => {
            const timestampWithOffset = '2025-01-11T12:00:00+05:00';
            const result = RunTimer.parseTimestamp(timestampWithOffset);

            expect(result).toBeInstanceOf(Date);
            expect(result).not.toBeNull();
            expect(result.getTime()).not.toBeNaN();
        });

        it('should handle ISO 8601 with milliseconds', () => {
            const timestampWithMs = '2025-01-11T12:00:00.123Z';
            const result = RunTimer.parseTimestamp(timestampWithMs);

            expect(result).toBeInstanceOf(Date);
            expect(result).not.toBeNull();
            expect(result.getTime()).not.toBeNaN();
        });

        it('should handle null/undefined input', () => {
            expect(RunTimer.parseTimestamp(null)).toBeNull();
            expect(RunTimer.parseTimestamp(undefined)).toBeNull();
        });

        it('should handle empty string', () => {
            expect(RunTimer.parseTimestamp('')).toBeNull();
        });

        it('should handle invalid timestamp format', () => {
            const invalidTimestamp = 'not-a-timestamp';
            const result = RunTimer.parseTimestamp(invalidTimestamp);

            expect(result).toBeNull();
        });

        it('should handle malformed ISO 8601', () => {
            const malformedTimestamp = '2025-13-45T25:61:61Z';
            const result = RunTimer.parseTimestamp(malformedTimestamp);

            // JavaScript Date is lenient and may still create a Date object
            // but it should be invalid (NaN getTime)
            if (result !== null) {
                expect(result.getTime()).toBeNaN();
            }
        });
    });

    describe('module structure', () => {
        it('should export expected public API', () => {
            expect(typeof RunTimer.initialize).toBe('function');
            expect(typeof RunTimer.shutdown).toBe('function');
            expect(typeof RunTimer.update).toBe('function');
            expect(typeof RunTimer.trackElement).toBe('function');
            expect(typeof RunTimer.formatDuration).toBe('function');
            expect(typeof RunTimer.parseTimestamp).toBe('function');
        });
    });
});
