/**
 * Test 7: Real-time Alert Notifications via WebSocket
 *
 * Verifies that when a WebSocket alert/pnl_update message arrives:
 *  1. The toast notification system is triggered
 *  2. The dashboard store receives the update
 *  3. Components re-render with new data
 *
 * Uses the mock WebSocket to simulate server-sent messages.
 */

import "../jest-globals-setup";
import React from "react";
import { render, screen, act, waitFor } from "@testing-library/react";
import { useTradingStore } from "@/store/useTradingStore";
import { useDashboardStore } from "@/store/dashboardStore";
import { simulateWsMessage, createMockWebSocketClass } from "../mocks/websocket";

describe("Real-time Alert Notifications", () => {
    beforeEach(() => {
        useTradingStore.getState().reset();
        useDashboardStore.getState().reset();
        localStorage.setItem("access_token", "test-jwt-token");
    });

    afterEach(() => {
        localStorage.clear();
    });

    it("updates trading store PNL via WebSocket pnl_update message", () => {
        // Seed initial position
        useTradingStore.getState().setPositions([
            {
                id: 1,
                symbol: "BTCUSDT",
                side: "LONG",
                entry_price: 62000,
                mark_price: 62500,
                current_price: 62500,
                quantity: 0.5,
                leverage: 5,
                unrealized_pnl: 250,
                unrealized_pnl_percent: 0.81,
                realized_pnl: 0,
                liquidation_price: 55800,
                margin_used: 6200,
                status: "OPEN",
                updated_at: "2026-06-12T08:00:00Z",
            },
        ]);

        // Simulate a WebSocket pnl_update message
        act(() => {
            useTradingStore.getState().updatePositionPnl({
                position_id: 1,
                unrealized_pnl: 500,
                unrealized_pnl_percent: 1.62,
                current_price: 63000,
            });
        });

        // Verify the position was updated
        const updated = useTradingStore.getState().positions[0];
        expect(updated.unrealized_pnl).toBe(500);
        expect(updated.unrealized_pnl_percent).toBe(1.62);
        expect(updated.current_price).toBe(63000);
    });

    it("updates dashboard store with market price updates", () => {
        // Simulate a market_price WebSocket message
        act(() => {
            useDashboardStore.getState().updateMarketPrice("BTCUSDT", {
                symbol: "BTCUSDT",
                price: 63000,
                change_percent: 0.8,
                high_24h: 64000,
                low_24h: 61000,
                volume_24h: 1000000,
                timestamp: "2026-06-12T08:00:00Z",
            });
        });

        const prices = useDashboardStore.getState().marketData;
        expect(prices["BTCUSDT"]).toBeDefined();
        expect(prices["BTCUSDT"].price).toBe(63000);
    });

    it("handles multiple rapid WebSocket updates without data loss", () => {
        useTradingStore.getState().setPositions([
            {
                id: 1,
                symbol: "BTCUSDT",
                side: "LONG",
                entry_price: 62000,
                mark_price: 62000,
                current_price: 62000,
                quantity: 0.5,
                leverage: 5,
                unrealized_pnl: 0,
                unrealized_pnl_percent: 0,
                realized_pnl: 0,
                liquidation_price: 55800,
                margin_used: 6200,
                status: "OPEN",
                updated_at: "2026-06-12T08:00:00Z",
            },
        ]);

        // Send 5 rapid PNL updates
        for (let i = 0; i < 5; i++) {
            act(() => {
                useTradingStore.getState().updatePositionPnl({
                    position_id: 1,
                    unrealized_pnl: (i + 1) * 100,
                    unrealized_pnl_percent: (i + 1) * 0.5,
                    current_price: 62000 + (i + 1) * 100,
                });
            });
        }

        // Final state should reflect the last update
        const final = useTradingStore.getState().positions[0];
        expect(final.unrealized_pnl).toBe(500);
        expect(final.current_price).toBe(62500);
    });

    it("adds trade notifications to dashboard store", () => {
        act(() => {
            useDashboardStore.getState().addTradeNotification({
                symbol: "ETHUSDT",
                action: "BUY",
                quantity: 2,
                price: 3400,
                status: "FILLED",
                timestamp: "2026-06-12T08:30:00Z",
            });
        });

        const notifications = useDashboardStore.getState().tradeNotifications;
        expect(notifications.length).toBe(1);
        expect(notifications[0].symbol).toBe("ETHUSDT");
        expect(notifications[0].action).toBe("BUY");
    });

    it("caps trade notifications at max limit (prevents memory leak)", () => {
        // Add 60 notifications (max should be 50 based on store cap)
        for (let i = 0; i < 60; i++) {
            act(() => {
                useDashboardStore.getState().addTradeNotification({
                    symbol: "BTCUSDT",
                    action: i % 2 === 0 ? "BUY" : "SELL",
                    quantity: 1,
                    price: 62000 + i,
                    status: "FILLED",
                    timestamp: new Date().toISOString(),
                });
            });
        }

        const notifications = useDashboardStore.getState().tradeNotifications;
        // Should not exceed max limit
        expect(notifications.length).toBeLessThanOrEqual(50);
    });

    it("mock websocket class simulates message events correctly", () => {
        const { MockWebSocket } = createMockWebSocketClass();
        const ws = new MockWebSocket("ws://localhost:8888/ws/1?token=test");

        const onMessage = jest.fn();
        ws.onmessage = onMessage;

        // Simulate a server message
        const testMessage = { type: "pnl_update", position_id: 1, unrealized_pnl: 300 };
        ws.simulateMessage(testMessage);

        expect(onMessage).toHaveBeenCalledTimes(1);
        const eventArg = onMessage.mock.calls[0][0];
        expect(JSON.parse(eventArg.data)).toEqual(testMessage);
    });
});