/**
 * WebSocket mock utilities using the `mock-socket` library.
 *
 * Provides:
 *  - createMockWebSocketClass(): factory for a mock WebSocket constructor
 *  - simulateWsMessage(ws, msg): helper to push a JSON message
 */

import { WebSocket } from "mock-socket";

/**
 * Create a fake WebSocket URL that matches the pattern used by useWebSocket's getWsUrl().
 */
export function createWsUrl(userId: number = 1, token: string = "test-token"): string {
    return `ws://localhost:8888/ws/${userId}?token=${token}`;
}

/**
 * Helper: push a JSON message to a mock WebSocket instance.
 */
export function simulateWsMessage(ws: WebSocket | any, message: Record<string, unknown>): void {
    if (ws.onmessage) {
        ws.onmessage(new MessageEvent("message", { data: JSON.stringify(message) }));
    } else {
        ws.dispatchEvent(new MessageEvent("message", { data: JSON.stringify(message) }));
    }
}

/**
 * Create a mock `WebSocket` class for testing useWebSocket hook.
 * Returns a mock constructor that can be injected via jest.spyOn.
 */
export function createMockWebSocketClass() {
    const instances: any[] = [];

    class MockWebSocket {
        url: string;
        readyState: number;
        onopen: ((event: Event) => void) | null = null;
        onclose: ((event: CloseEvent) => void) | null = null;
        onmessage: ((event: MessageEvent) => void) | null = null;
        onerror: ((event: Event) => void) | null = null;
        send = jest.fn();
        close = jest.fn();
        addEventListener = jest.fn();
        removeEventListener = jest.fn();
        dispatchEvent = jest.fn();

        static CONNECTING = 0;
        static OPEN = 1;
        static CLOSING = 2;
        static CLOSED = 3;

        constructor(url: string) {
            this.url = url;
            this.readyState = WebSocket.CONNECTING;
            instances.push(this);
        }

        // Test helpers
        simulateOpen(): void {
            this.readyState = WebSocket.OPEN;
            this.onopen?.(new Event("open"));
        }

        simulateMessage(data: Record<string, unknown>): void {
            this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(data) }));
        }

        simulateClose(code: number = 1000, reason: string = ""): void {
            this.readyState = WebSocket.CLOSED;
            this.onclose?.(new CloseEvent("close", { code, reason, wasClean: true }));
        }

        simulateError(): void {
            this.onerror?.(new Event("error"));
        }
    }

    return {
        MockWebSocket,
        getInstances: () => instances,
    };
}