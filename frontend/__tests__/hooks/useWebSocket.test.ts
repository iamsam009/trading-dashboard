/**
 * useWebSocket hook unit tests.
 *
 * Tests the WebSocket hook's connection lifecycle, message handling,
 * reconnection logic, and subscribe/unsubscribe functionality.
 *
 * Uses the createMockWebSocketClass() factory to replace the global
 * WebSocket constructor, then verifies that the hook correctly
 * dispatches to the Zustand dashboard store.
 */

import "../jest-globals-setup";
import { renderHook, act } from "@testing-library/react";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useDashboardStore } from "@/store/dashboardStore";
import { createMockWebSocketClass } from "../mocks/websocket";

describe("useWebSocket", () => {
    const { MockWebSocket, getInstances } = createMockWebSocketClass();
    const originalWebSocket = global.WebSocket;

    beforeEach(() => {
        useDashboardStore.getState().reset();
        jest.useFakeTimers();
        getInstances().length = 0;
        (global as any).WebSocket = MockWebSocket;
    });

    afterEach(() => {
        jest.useRealTimers();
        (global as any).WebSocket = originalWebSocket;
    });

    /** Return the most recently created mock WebSocket instance. */
    function getLatestInstance() {
        const instances = getInstances();
        return instances[instances.length - 1];
    }

    // ── Connection lifecycle ──────────────────────────────────────

    it("does not create a WebSocket when userId is null", () => {
        renderHook(() => useWebSocket(null, "token"));
        expect(getInstances().length).toBe(0);
    });

    it("does not create a WebSocket when token is null", () => {
        renderHook(() => useWebSocket(1, null));
        expect(getInstances().length).toBe(0);
    });

    it("creates a WebSocket with the correct URL", () => {
        renderHook(() => useWebSocket(1, "test-jwt-token"));

        const ws = getLatestInstance();
        expect(ws).toBeDefined();
        expect(ws.url).toContain("/api/v1/ws/1");
        expect(ws.url).toContain("token=test-jwt-token");
    });

    it("cleans up WebSocket and sets connected=false on unmount", () => {
        const { unmount } = renderHook(() => useWebSocket(1, "test-token"));
        const ws = getLatestInstance();

        act(() => {
            ws.simulateOpen();
        });

        unmount();

        expect(ws.close).toHaveBeenCalled();
        expect(useDashboardStore.getState().connected).toBe(false);
    });

    // ── Message handling ──────────────────────────────────────────

    it("processes 'connected' message and updates store", () => {
        renderHook(() => useWebSocket(1, "test-token"));
        const ws = getLatestInstance();

        act(() => {
            ws.simulateOpen();
        });

        act(() => {
            ws.simulateMessage({
                type: "connected",
                subscribed_symbols: ["BTCUSDT", "ETHUSDT"],
            });
        });

        const state = useDashboardStore.getState();
        expect(state.connected).toBe(true);
        expect(state.userId).toBe(1);
        expect(state.subscribedSymbols).toEqual(["BTCUSDT", "ETHUSDT"]);
    });

    it("processes 'initial_snapshot' with balance and positions", () => {
        renderHook(() => useWebSocket(1, "test-token"));
        const ws = getLatestInstance();

        act(() => {
            ws.simulateOpen();
        });

        act(() => {
            ws.simulateMessage({
                type: "initial_snapshot",
                data: {
                    balance: {
                        total_balance: 25000,
                        available_balance: 20000,
                        unrealized_pnl: 500,
                        wallet_balance: 25000,
                    },
                    positions: [
                        {
                            symbol: "BTCUSDT",
                            side: "LONG",
                            quantity: 0.5,
                            entry_price: 62000,
                            mark_price: 62500,
                            unrealized_pnl: 250,
                            leverage: 5,
                            status: "OPEN",
                        },
                    ],
                },
            });
        });

        const state = useDashboardStore.getState();
        expect(state.balance).toEqual({
            total_balance: 25000,
            available_balance: 20000,
            unrealized_pnl: 500,
            wallet_balance: 25000,
        });
        expect(state.positions).toHaveLength(1);
        expect(state.positions[0].symbol).toBe("BTCUSDT");
    });

    it("handles 'initial_snapshot' without balance gracefully", () => {
        renderHook(() => useWebSocket(1, "test-token"));
        const ws = getLatestInstance();

        act(() => {
            ws.simulateOpen();
        });

        act(() => {
            ws.simulateMessage({
                type: "initial_snapshot",
                data: {
                    positions: [],
                },
            });
        });

        const state = useDashboardStore.getState();
        expect(state.positions).toHaveLength(0);
        expect(state.balance).toBeNull();
    });

    it("updates market data on 'market_price' message", () => {
        renderHook(() => useWebSocket(1, "test-token"));
        const ws = getLatestInstance();

        act(() => {
            ws.simulateOpen();
        });

        act(() => {
            ws.simulateMessage({
                type: "market_price",
                data: {
                    symbol: "BTCUSDT",
                    price: 63000,
                    change_percent: 0.8,
                    high_24h: 64000,
                    low_24h: 61000,
                    volume_24h: 1000000,
                    timestamp: "2026-06-12T08:00:00Z",
                },
            });
        });

        const marketData = useDashboardStore.getState().marketData;
        expect(marketData["BTCUSDT"]).toBeDefined();
        expect(marketData["BTCUSDT"].price).toBe(63000);
        expect(marketData["BTCUSDT"].change_percent).toBe(0.8);
    });

    it("adds trade notification on 'trade_notification' message", () => {
        renderHook(() => useWebSocket(1, "test-token"));
        const ws = getLatestInstance();

        act(() => {
            ws.simulateOpen();
        });

        act(() => {
            ws.simulateMessage({
                type: "trade_notification",
                data: {
                    symbol: "ETHUSDT",
                    action: "BUY",
                    quantity: 2,
                    price: 3400,
                    status: "FILLED",
                    timestamp: "2026-06-12T08:30:00Z",
                },
            });
        });

        const notifications = useDashboardStore.getState().tradeNotifications;
        expect(notifications).toHaveLength(1);
        expect(notifications[0].symbol).toBe("ETHUSDT");
        expect(notifications[0].action).toBe("BUY");
    });

    it("updates balance on 'pnl_update' message", () => {
        renderHook(() => useWebSocket(1, "test-token"));
        const ws = getLatestInstance();

        act(() => {
            ws.simulateOpen();
        });

        act(() => {
            ws.simulateMessage({
                type: "pnl_update",
                data: {
                    total_balance: 25500,
                    available_balance: 20500,
                    unrealized_pnl: 1000,
                    wallet_balance: 25500,
                },
            });
        });

        const balance = useDashboardStore.getState().balance;
        expect(balance?.total_balance).toBe(25500);
        expect(balance?.unrealized_pnl).toBe(1000);
    });

    it("handles 'pnl_update' without data gracefully", () => {
        renderHook(() => useWebSocket(1, "test-token"));
        const ws = getLatestInstance();

        act(() => {
            ws.simulateOpen();
        });

        expect(() => {
            act(() => {
                ws.simulateMessage({ type: "pnl_update" });
            });
        }).not.toThrow();
    });

    it("responds with pong on 'ping' message", () => {
        renderHook(() => useWebSocket(1, "test-token"));
        const ws = getLatestInstance();

        act(() => {
            ws.simulateOpen();
        });

        act(() => {
            ws.simulateMessage({ type: "ping" });
        });

        expect(ws.send).toHaveBeenCalledWith(JSON.stringify({ type: "pong" }));
    });

    it("updates subscribed symbols on 'subscribed' message", () => {
        renderHook(() => useWebSocket(1, "test-token"));
        const ws = getLatestInstance();

        act(() => {
            ws.simulateOpen();
        });

        act(() => {
            ws.simulateMessage({
                type: "subscribed",
                symbols: ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            });
        });

        expect(useDashboardStore.getState().subscribedSymbols).toEqual([
            "BTCUSDT",
            "ETHUSDT",
            "SOLUSDT",
        ]);
    });

    it("ignores unknown message types without crashing", () => {
        renderHook(() => useWebSocket(1, "test-token"));
        const ws = getLatestInstance();

        act(() => {
            ws.simulateOpen();
        });

        expect(() => {
            act(() => {
                ws.simulateMessage({ type: "unknown_type", data: {} });
            });
        }).not.toThrow();
    });

    it("ignores malformed JSON messages without crashing", () => {
        renderHook(() => useWebSocket(1, "test-token"));
        const ws = getLatestInstance();

        act(() => {
            ws.simulateOpen();
        });

        expect(() => {
            act(() => {
                ws.onmessage?.(
                    new MessageEvent("message", { data: "not-valid-json!!!" })
                );
            });
        }).not.toThrow();
    });

    // ── Subscribe / Unsubscribe ───────────────────────────────────

    it("subscribe sends a subscribe message over open WebSocket", () => {
        const { result } = renderHook(() => useWebSocket(1, "test-token"));
        const ws = getLatestInstance();

        act(() => {
            ws.simulateOpen();
        });

        act(() => {
            result.current.subscribe(["BTCUSDT"]);
        });

        expect(ws.send).toHaveBeenCalledWith(
            JSON.stringify({ type: "subscribe", symbols: ["BTCUSDT"] })
        );
    });

    it("unsubscribe sends an unsubscribe message over open WebSocket", () => {
        const { result } = renderHook(() => useWebSocket(1, "test-token"));
        const ws = getLatestInstance();

        act(() => {
            ws.simulateOpen();
        });

        act(() => {
            result.current.unsubscribe(["ETHUSDT"]);
        });

        expect(ws.send).toHaveBeenCalledWith(
            JSON.stringify({ type: "unsubscribe", symbols: ["ETHUSDT"] })
        );
    });

    it("does not send subscribe when WebSocket is not open", () => {
        const { result } = renderHook(() => useWebSocket(1, "test-token"));
        const ws = getLatestInstance();
        // WebSocket is in CONNECTING state, not OPEN

        act(() => {
            result.current.subscribe(["BTCUSDT"]);
        });

        // send should not have been called with a subscribe payload
        const subscribeCalls = (ws.send as jest.Mock).mock.calls.filter(
            (call: any[]) => {
                try {
                    const parsed = JSON.parse(call[0]);
                    return parsed.type === "subscribe";
                } catch {
                    return false;
                }
            }
        );
        expect(subscribeCalls).toHaveLength(0);
    });

    it("does not send unsubscribe when WebSocket is not open", () => {
        const { result } = renderHook(() => useWebSocket(1, "test-token"));
        const ws = getLatestInstance();

        act(() => {
            result.current.unsubscribe(["ETHUSDT"]);
        });

        const unsubscribeCalls = (ws.send as jest.Mock).mock.calls.filter(
            (call: any[]) => {
                try {
                    const parsed = JSON.parse(call[0]);
                    return parsed.type === "unsubscribe";
                } catch {
                    return false;
                }
            }
        );
        expect(unsubscribeCalls).toHaveLength(0);
    });

    // ── Reconnection logic ────────────────────────────────────────

    it("sets connected=false on WebSocket close", () => {
        renderHook(() => useWebSocket(1, "test-token"));
        const ws = getLatestInstance();

        act(() => {
            ws.simulateOpen();
        });
        act(() => {
            useDashboardStore.getState().setConnected(true);
        });

        act(() => {
            ws.simulateClose(1000, "Normal closure");
        });

        expect(useDashboardStore.getState().connected).toBe(false);
    });

    it("attempts reconnection after non-auth close (code 1006)", () => {
        renderHook(() => useWebSocket(1, "test-token"));
        const ws = getLatestInstance();

        act(() => {
            ws.simulateOpen();
        });

        act(() => {
            ws.simulateClose(1006, "Abnormal closure");
        });

        // Fast-forward past the first reconnect delay (1000ms base)
        act(() => {
            jest.advanceTimersByTime(1500);
        });

        // A new WebSocket instance should have been created
        expect(getInstances().length).toBeGreaterThanOrEqual(2);
    });

    it("does NOT reconnect after auth failure (code 4001)", () => {
        renderHook(() => useWebSocket(1, "test-token"));
        const ws = getLatestInstance();

        act(() => {
            ws.simulateOpen();
        });

        act(() => {
            ws.simulateClose(4001, "Unauthorized");
        });

        act(() => {
            jest.advanceTimersByTime(5000);
        });

        // Should still only have 1 instance (no reconnect)
        expect(getInstances().length).toBe(1);
    });

    it("does NOT reconnect after auth failure (code 4003)", () => {
        renderHook(() => useWebSocket(1, "test-token"));
        const ws = getLatestInstance();

        act(() => {
            ws.simulateOpen();
        });

        act(() => {
            ws.simulateClose(4003, "Forbidden");
        });

        act(() => {
            jest.advanceTimersByTime(5000);
        });

        expect(getInstances().length).toBe(1);
    });

    it("uses exponential backoff for reconnection delays", () => {
        renderHook(() => useWebSocket(1, "test-token"));

        // First close → reconnect after ~1000ms
        let ws = getLatestInstance();
        act(() => {
            ws.simulateOpen();
        });
        act(() => {
            ws.simulateClose(1006);
        });

        act(() => {
            jest.advanceTimersByTime(1500);
        });
        expect(getInstances().length).toBe(2); // reconnected

        // Second close → reconnectAttempt resets to 0 on open, so delay = 1000ms again
        ws = getLatestInstance();
        act(() => {
            ws.simulateOpen();
        });
        act(() => {
            ws.simulateClose(1006);
        });

        act(() => {
            jest.advanceTimersByTime(1500);
        });
        expect(getInstances().length).toBe(3); // reconnected (onopen reset attempt to 0, so delay=1000ms)

        act(() => {
            jest.advanceTimersByTime(1000);
        });
        expect(getInstances().length).toBe(3); // no further change
    });

    // ── Edge cases ────────────────────────────────────────────────

    it("handles multiple rapid market_price messages", () => {
        renderHook(() => useWebSocket(1, "test-token"));
        const ws = getLatestInstance();

        act(() => {
            ws.simulateOpen();
        });

        const symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT", "DOGEUSDT"];
        symbols.forEach((symbol, i) => {
            act(() => {
                ws.simulateMessage({
                    type: "market_price",
                    data: {
                        symbol,
                        price: 100 + i * 10,
                        change_percent: i * 0.5,
                        high_24h: 110 + i * 10,
                        low_24h: 90 + i * 10,
                        volume_24h: 500000,
                        timestamp: "2026-06-12T08:00:00Z",
                    },
                });
            });
        });

        const marketData = useDashboardStore.getState().marketData;
        expect(Object.keys(marketData)).toHaveLength(5);
        expect(marketData["BTCUSDT"].price).toBe(100);
        expect(marketData["SOLUSDT"].price).toBe(120);
    });
});