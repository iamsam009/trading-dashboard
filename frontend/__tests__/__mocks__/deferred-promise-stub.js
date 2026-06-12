/**
 * Stub for the "@open-draft/deferred-promise" ESM-only package.
 *
 * MSW v2 uses DeferredPromise internally for WebSocket client management.
 * Jest+SWC cannot parse the .mjs file; stub it with a CJS equivalent.
 */

"use strict";

/**
 * Creates a deferred executor with resolve/reject controls.
 */
function createDeferredExecutor() {
    let resolve, reject;
    const executor = (res, rej) => {
        executor.state = "pending";
        executor.resolve = (data) => {
            if (executor.state !== "pending") return;
            executor.result = data;
            const onFulfilled = (value) => {
                executor.state = "fulfilled";
                return value;
            };
            return res(
                data instanceof Promise
                    ? data
                    : Promise.resolve(data).then(onFulfilled)
            );
        };
        executor.reject = (reason) => {
            if (executor.state !== "pending") return;
            queueMicrotask(() => {
                executor.state = "rejected";
            });
            return rej((executor.rejectionReason = reason));
        };
    };
    return executor;
}

class DeferredPromise extends Promise {
    #executor;
    resolve;
    reject;

    constructor(executor = null) {
        const deferredExecutor = createDeferredExecutor();
        super((originalResolve, originalReject) => {
            deferredExecutor(originalResolve, originalReject);
            executor?.(deferredExecutor.resolve, deferredExecutor.reject);
        });
        this.#executor = deferredExecutor;
        this.resolve = this.#executor.resolve;
        this.reject = this.#executor.reject;
    }

    get state() {
        return this.#executor.state;
    }

    get rejectionReason() {
        return this.#executor.rejectionReason;
    }

    then(onFulfilled, onRejected) {
        return this.#decorate(super.then(onFulfilled, onRejected));
    }

    catch(onRejected) {
        return this.#decorate(super.catch(onRejected));
    }

    finally(onfinally) {
        return this.#decorate(super.finally(onfinally));
    }

    #decorate(promise) {
        const self = this;
        return Object.defineProperties(promise, {
            resolve: {
                configurable: true,
                get() { return self.resolve; },
            },
            reject: {
                configurable: true,
                get() { return self.reject; },
            },
        });
    }
}

module.exports = { DeferredPromise, createDeferredExecutor };