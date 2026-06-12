/**
 * Custom Jest test environment – extends jsdom to inject Node.js Web API
 * globals that jsdom strips away.
 *
 * MSW v2 (and its dependency @mswjs/interceptors) needs these at
 * module-init time.  jsdom's global scope doesn't include them, so MSW
 * crashes with "ReferenceError: Request/TextEncoder is not defined".
 *
 * This environment adds them in its async setup() hook, which runs AFTER
 * jsdom is initialized but BEFORE the test module is loaded/executed.
 */
import { TestEnvironment as JsdomEnvironment } from "jest-environment-jsdom";

export default class JsdomExtendedEnvironment extends JsdomEnvironment {
    async setup() {
        await super.setup();

        // jsdom strips Node.js built-in globals; restore them so MSW v2 works.
        const g = this.global as unknown as Record<string, unknown>;
        const gt = globalThis as Record<string, unknown>;

        // Fetch API
        if (typeof this.global.Request === "undefined") {
            g.Request = Request;
        }
        if (typeof this.global.Response === "undefined") {
            g.Response = Response;
        }
        if (typeof this.global.Headers === "undefined") {
            g.Headers = Headers;
        }
        if (typeof this.global.fetch === "undefined") {
            g.fetch = fetch;
        }

        // Encoding API
        if (typeof this.global.TextEncoder === "undefined") {
            g.TextEncoder = gt.TextEncoder ?? TextEncoder;
        }
        if (typeof this.global.TextDecoder === "undefined") {
            g.TextDecoder = gt.TextDecoder ?? TextDecoder;
        }

        // Streams API (used by MSW interceptors for fetch decompression)
        // Available as Node.js globals in v18+ (stream/web) but stripped by jsdom.
        if (typeof this.global.TransformStream === "undefined") {
            g.TransformStream = gt.TransformStream ?? (() => {
                const { TransformStream: TS } = require("node:stream/web") as typeof import("node:stream/web");
                return TS;
            })();
        }
        if (typeof this.global.ReadableStream === "undefined") {
            g.ReadableStream = gt.ReadableStream ?? (() => {
                const { ReadableStream: RS } = require("node:stream/web") as typeof import("node:stream/web");
                return RS;
            })();
        }
        if (typeof this.global.WritableStream === "undefined") {
            g.WritableStream = gt.WritableStream ?? (() => {
                const { WritableStream: WS } = require("node:stream/web") as typeof import("node:stream/web");
                return WS;
            })();
        }
        if (typeof this.global.CompressionStream === "undefined") {
            g.CompressionStream = gt.CompressionStream ?? (() => {
                const { CompressionStream: CS } = require("node:stream/web") as typeof import("node:stream/web");
                return CS;
            })();
        }
        if (typeof this.global.DecompressionStream === "undefined") {
            g.DecompressionStream = gt.DecompressionStream ?? (() => {
                const { DecompressionStream: DS } = require("node:stream/web") as typeof import("node:stream/web");
                return DS;
            })();
        }

        // AbortController / AbortSignal
        if (typeof this.global.AbortController === "undefined") {
            g.AbortController = gt.AbortController ?? AbortController;
        }
        if (typeof this.global.AbortSignal === "undefined") {
            g.AbortSignal = gt.AbortSignal ?? AbortSignal;
        }

        // BroadcastChannel – browser API used by MSW's WebSocket client manager
        // for cross-tab coordination. jsdom doesn't provide it.  Provide a
        // no-op stub so MSW's ws.js module loads without crashing.
        if (typeof this.global.BroadcastChannel === "undefined") {
            g.BroadcastChannel = class BroadcastChannel {
                name: string;
                onmessage: ((ev: MessageEvent) => any) | null = null;
                onmessageerror: ((ev: MessageEvent) => any) | null = null;
                constructor(name: string) { this.name = name; }
                postMessage(_message: any) { }
                addEventListener(_type: string, _listener: EventListener) { }
                removeEventListener(_type: string, _listener: EventListener) { }
                close() { }
                unref() { return this; }
                ref() { return this; }
            };
        }
    }
}