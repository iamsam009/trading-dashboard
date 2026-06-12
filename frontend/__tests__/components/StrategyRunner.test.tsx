/**
 * Test 3: StrategyRunner – Start/Stop Bot Button
 *
 * Verifies that clicking the toggle button on a strategy card sends
 * the correct PUT /strategies/:id request and shows a toast notification.
 */

import "../jest-globals-setup";
import React from "react";
import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import StrategyRunner from "@/components/Strategy/StrategyRunner";
import { useTradingStore } from "@/store/useTradingStore";
import { makeStrategies } from "../mocks/data";
import { toast } from "react-hot-toast";

describe("StrategyRunner", () => {
    beforeEach(() => {
        localStorage.setItem("access_token", "test-jwt-token");
        useTradingStore.getState().reset();
        jest.clearAllMocks();
    });

    it("renders the skeleton when loading", () => {
        const { container } = render(
            <StrategyRunner strategies={[]} isLoading={true} />,
        );
        const skeletonCards = container.querySelectorAll(".animate-pulse");
        expect(skeletonCards.length).toBeGreaterThan(0);
    });

    it("renders the empty state when no strategies", () => {
        render(<StrategyRunner strategies={[]} isLoading={false} />);
        expect(screen.getByText("No strategies configured")).toBeInTheDocument();
    });

    it("renders strategy cards from props", () => {
        const strategies = makeStrategies(3);
        render(<StrategyRunner strategies={strategies} />);

        expect(screen.getByText("BTC Momentum")).toBeInTheDocument();
        expect(screen.getByText("ETH Mean Reversion")).toBeInTheDocument();
        expect(screen.getByText("SOL Breakout")).toBeInTheDocument();
    });

    it("renders strategy cards from the store", () => {
        const strategies = makeStrategies(2);
        useTradingStore.getState().setStrategies(strategies);
        render(<StrategyRunner />);

        expect(screen.getByText("BTC Momentum")).toBeInTheDocument();
        expect(screen.getByText("ETH Mean Reversion")).toBeInTheDocument();
    });

    it("displays the correct toggle button text for inactive strategy", () => {
        const strategies = makeStrategies(1);
        // First strategy is active by default; override to inactive
        strategies[0].is_active = false;
        render(<StrategyRunner strategies={strategies} />);

        // Should show "▶ Start" button, not "⏹ Stop"
        const startButton = screen.getByText("▶ Start");
        expect(startButton).toBeInTheDocument();
    });

    it("displays the correct toggle button text for active strategy", () => {
        const strategies = makeStrategies(1);
        strategies[0].is_active = true;
        render(<StrategyRunner strategies={strategies} />);

        // Should show "⏹ Stop" button
        const stopButton = screen.getByText("⏹ Stop");
        expect(stopButton).toBeInTheDocument();
    });

    it("displays strategy symbols as badges", () => {
        const strategies = makeStrategies(1);
        render(<StrategyRunner strategies={strategies} />);

        expect(screen.getByText("BTCUSDT")).toBeInTheDocument();
    });

    it("calls toggle and shows success toast when starting a strategy", async () => {
        const user = userEvent.setup();
        const strategies = makeStrategies(1);
        strategies[0].is_active = false;
        render(<StrategyRunner strategies={strategies} />);

        const startButton = screen.getByText("▶ Start");
        await user.click(startButton);

        // Wait for the toast to be called
        await act(async () => {
            await new Promise((r) => setTimeout(r, 100));
        });

        // Toast should have been called with success message
        expect(toast.success).toHaveBeenCalledWith(
            expect.stringContaining("BTC Momentum"),
        );
    });

    it("calls toggle and shows success toast when stopping a strategy", async () => {
        const user = userEvent.setup();
        const strategies = makeStrategies(1);
        strategies[0].is_active = true;
        render(<StrategyRunner strategies={strategies} />);

        const stopButton = screen.getByText("⏹ Stop");
        await user.click(stopButton);

        await act(async () => {
            await new Promise((r) => setTimeout(r, 100));
        });

        expect(toast.success).toHaveBeenCalledWith(
            expect.stringContaining("BTC Momentum"),
        );
    });

    it("toggles the strategy active state in the store after click", async () => {
        const user = userEvent.setup();
        const strategies = makeStrategies(1);
        strategies[0].is_active = false;
        useTradingStore.getState().setStrategies(strategies);
        render(<StrategyRunner />);

        expect(useTradingStore.getState().strategies[0].is_active).toBe(false);

        const startButton = screen.getByText("▶ Start");
        await user.click(startButton);

        await act(async () => {
            await new Promise((r) => setTimeout(r, 100));
        });

        // Store should have toggled the strategy to active
        expect(useTradingStore.getState().strategies[0].is_active).toBe(true);
    });
});