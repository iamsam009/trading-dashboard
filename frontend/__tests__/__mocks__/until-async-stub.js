/**
 * Stub for the "until-async" ESM-only package.
 *
 * MSW v2's lib/core/experimental/frames/http-frame.js uses:
 *   var import_until_async = require("until-async");
 *
 * This CJS stub provides the `until` function that wraps a promise
 * callback and returns [error, result] tuple.
 */

"use strict";

/**
 * Gracefully handles a callback that returns a promise.
 * Returns [error, result] tuple.
 */
async function until(callback) {
    try {
        const result = await callback();
        return [null, result];
    } catch (error) {
        return [error, null];
    }
}

module.exports = { until };