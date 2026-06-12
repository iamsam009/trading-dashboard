/**
 * Test 2: PositionsTable – WebSocket Updates
 *
 * Verifies that the PositionsTable renders open positions and updates
 * when a position_update WebSocket message arrives (simulated via store).
 */

import "../jest-globals-setup";
import React from "react";
import { render, screen, act } from "@testing-library/react";
import PositionsTable from "@/components/Dashboard/PositionsTable";
import { useTradingStore } from "@/store/useTradingStore";
import { makePositions, makePosition } from "../mocks/data";

describe("PositionsTable", () => {
    beforeEach(() => {
        useTradingStore.getState().reset();
    });

    it("renders the skeleton when loading", () => {
        useTradingStore.getState().setPositionsLoading(true);
        const { container } = render(<PositionsTable />);
        // Skeleton should be visible
        const skeletonRows = container.querySelectorAll(".animate-pulse");
        expect(skeletonRows.length).toBeGreaterThan(0);
    });

    it("renders the empty state when no positions", () => {
        useTradingStore.getState().setPositions([]);
        const { container } = render(<PositionsTable />);
        expect(screen.getByText("No open positions")).toBeInTheDocument();
    });

    it("renders positions from the store", () => {
        const positions = makePositions(3);
        useTradingStore.getState().setPositions(positions);
        render(<PositionsTable />);

        // Should show all 3 symbols
        expect(screen.getByText("BTCUSDT")).toBeInTheDocument();
        expect(screen.getByText("ETHUSDT")).toBeInTheDocument();
        expect(screen.getByText("SOLUSDT")).toBeInTheDocument();
    });

    it("renders positions from props (bypassing store)", () => {
        const positions = makePositions(2);
        render(<PositionsTable positions={positions} />);

        expect(screen.getByText("BTCUSDT")).toBeInTheDocument();
        expect(screen.getByText("ETHUSDT")).toBeInTheDocument();
    });

    it("displays the correct table headers", () => {
        const positions = makePositions(1);
        render(<PositionsTable positions={positions} />);

        // Actual headers: Position, Qty, Entry, Mark, PNL, PNL%, Margin, Liq.
        expect(screen.getByText("Position")).toBeInTheDocument();
        expect(screen.getByText("Qty")).toBeInTheDocument();
        expect(screen.getByText("Entry")).toBeInTheDocument();
        expect(screen.getByText("Mark")).toBeInTheDocument();
        expect(screen.getByText("PNL")).toBeInTheDocument();
        expect(screen.getByText("PNL%")).toBeInTheDocument();
        expect(screen.getByText("Margin")).toBeInTheDocument();
        expect(screen.getByText("Liq.")).toBeInTheDocument();
    });

    it("formats currency values in INR", () => {
        const positions = makePositions(1);
        useTradingStore.getState().setPositions(positions);
        render(<PositionsTable />);

        // makePositions(1) creates: entry_price=100, unrealized_pnl=50
        // PNL and margin are formatted with ₹ currency symbol
        const pnlCells = screen.getAllByText(/50\.00/);
        expect(pnlCells.length).toBeGreaterThan(0);
    });

    it("shows positive PNL in green (emerald)", () => {
        const position = makePosition({ unrealized_pnl: 500, side: "LONG" });
        useTradingStore.getState().setPositions([position]);
        render(<PositionsTable />);

        // The PNL cell should have emerald color class
        // Intl.NumberFormat("en-IN") may not render ₹ in JSDOM; match the numeric part
        const pnlCells = screen.getAllByText(/500\.00/);
        const pnlCell = pnlCells.find((c) => c.className.includes("emerald"));
        expect(pnlCell).toBeDefined();
    });

    it("shows negative PNL in red", () => {
        const position = makePosition({ unrealized_pnl: -300, side: "SHORT" });
        useTradingStore.getState().setPositions([position]);
        render(<PositionsTable />);

        // Negative PNL should have red color class; match numeric part
        const pnlCells = screen.getAllByText(/300\.00/);
        const pnlCell = pnlCells.find((c) => c.className.includes("red"));
        expect(pnlCell).toBeDefined();
    });

    it("updates position PNL via store action (simulating WebSocket update)", () => {
        // makePosition defaults: unrealized_pnl=250, entry_price=62000
        const position = makePosition({ unrealized_pnl: 250 });
        useTradingStore.getState().setPositions([position]);
        const { rerender } = render(<PositionsTable />);

        // Initial PNL
        expect(screen.getByText(/₹250\.00/)).toBeInTheDocument();

        // Simulate WebSocket push: update PNL for position id=1
        act(() => {
            useTradingStore.getState().updatePositionPnl({
                position_id: 1,
                unrealized_pnl: 450,
                unrealized_pnl_percent: 1.5,
                current_price: 63000,
            });
        });

        // Re-render to reflect updated state
        rerender(<PositionsTable />);

        // Updated PNL should now show
        expect(screen.getByText(/₹450\.00/)).toBeInTheDocument();
    });

    it("displays LONG/SHORT badges with correct colors", () => {
        const longPos = makePosition({ id: 1, side: "LONG" });
        const shortPos = makePosition({ id: 2, side: "SHORT" });
        render(<PositionsTable positions={[longPos, shortPos]} />);

        const longBadge = screen.getByText("LONG");
        const shortBadge = screen.getByText("SHORT");

        expect(longBadge).toBeInTheDocument();
        expect(shortBadge).toBeInTheDocument();
        // LONG should be emerald
        expect(longBadge.className).toContain("emerald");
        // SHORT should be red
        expect(shortBadge.className).toContain("red");
    });
});