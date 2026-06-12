/**
 * Stub for the "rettime" ESM-only package.
 *
 * MSW v2's lib/core/experimental/sources/network-source.js uses:
 *   var import_rettime = require("rettime");
 *
 * It then:
 *   1. Extends import_rettime.TypedEvent (which extends MessageEvent)
 *   2. Instantiates new import_rettime.Emitter()
 *
 * This CJS stub provides the minimal surface needed for MSW to load
 * without hitting ESM import errors in Jest.
 */

"use strict";

// ---------------------------------------------------------------------------
// TypedEvent – extends MessageEvent (or a compatible stand-in)
// ---------------------------------------------------------------------------
class TypedEvent extends MessageEvent {
    /**
     * MSW's NetworkFrameEvent calls: super(...[type, {}])
     * which is equivalent to super(type, {})
     */
    constructor(type, init) {
        super(type, init || {});
    }
}

// ---------------------------------------------------------------------------
// Emitter – minimal event emitter with the surface MSW actually calls
// ---------------------------------------------------------------------------
class Emitter {
    #listeners = new Map();

    constructor() {
        this.#listeners = new Map();
    }

    /**
     * Called by define-network.js (wildcard forwarding):
     *   events.emit(event)   – synchronously dispatch to all matching listeners
     *
     * Also called on frame.events:
     *   httpFrame.events.emit(new ResponseEvent(...))     // interceptor-source.js:76
     *   this.events.emit(new WebSocketConnectionEvent(...)) // websocket-frame.js:62
     *   this.events.emit(new UnhandledWebSocketExceptionEvent(...)) // websocket-frame.js:95
     *
     * Returns true if any listeners were called, false otherwise.
     */
    emit(event) {
        let dispatched = false;

        // Emit to listeners registered for this specific event type.
        const handlers = this.#listeners.get(event.type);
        if (handlers && handlers.size > 0) {
            for (const fn of handlers) {
                fn(event);
            }
            dispatched = true;
        }

        // Emit to wildcard "*" listeners (used by define-network.js to forward
        // frame events to the network-level emitter).
        const wildcard = this.#listeners.get("*");
        if (wildcard && wildcard.size > 0) {
            for (const fn of wildcard) {
                fn(event);
            }
            dispatched = true;
        }

        return dispatched;
    }

    /**
     * Called by network-source.ts:
     *   await this.emitter.emitAsPromise(new NetworkFrameEvent('frame', frame))
     *
     * Returns a Promise that resolves after calling all listeners.
     */
    emitAsPromise(event) {
        const type = event.type;
        const handlers = this.#listeners.get(type);
        if (!handlers || handlers.size === 0) {
            return Promise.resolve();
        }
        const results = [];
        for (const fn of handlers) {
            results.push(fn(event));
        }
        return Promise.all(results).then(() => undefined);
    }

    /**
     * Called by network-source.ts and define-network.js:
     *   this.emitter.on(type, listener, options)
     *
     * Supports wildcard "*" type for catch-all listeners (define-network.js:92).
     */
    on(type, listener, _options) {
        if (!this.#listeners.has(type)) {
            this.#listeners.set(type, new Set());
        }
        this.#listeners.get(type).add(listener);
        return this;
    }

    /**
     * Called by network-source.ts and interceptor-source.js:
     *   this.emitter.removeAllListeners()
     */
    removeAllListeners() {
        this.#listeners.clear();
        return this;
    }
}

// ---------------------------------------------------------------------------
// TypedListenerOptions – TS-only type; not needed at runtime, but exported
// for completeness to match the rettime package surface.
// ---------------------------------------------------------------------------
const TypedListenerOptions = {};

module.exports = {
    Emitter,
    TypedEvent,
    TypedListenerOptions,
};