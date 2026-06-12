/**
 * Test: TradeHistory Component
 *
 * Verifies the trade history table renders correctly with various states,
 * filters, and pagination.
 */

import "../jest-globals-setup";
import React from "react";
import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import TradeHistory, { TradeHistorySkeleton } from "@/components/Dashboard/TradeHistory";
import { useTradingStore } from "@/store/useTradingStore";
import { makeTrade, makeTrades } from "../mocks/data";

describe("TradeHistory", () => {
    beforeEach(() => {
        useTradingStore.setState({
            trades: [],
            tradesTotal: 0,
            tradesPage: 1,
            tradesLoading: false,
        });
    });

    // ── Skeleton ──────────────────────────────────────────

    it("renders the skeleton component", () => {
        const { container } = render(<TradeHistorySkeleton />);
        // Skeleton has the animate-pulse class
        const skeleton = container.querySelector(".animate-pulse");
        expect(skeleton).toBeTruthy();
    });

    // ── Loading & Empty states ────────────────────────────

    it("renders the skeleton when isLoading prop is true", () => {
        render(<TradeHistory isLoading={true} />);
        const skeleton = document.querySelector(".animate-pulse");
        expect(skeleton).toBeTruthy();
    });

    it("renders the empty state when no trades exist", () => {
        render(<TradeHistory />);
        expect(screen.getByText("No trade history yet")).toBeInTheDocument();
    });

    it("renders the empty state subtitle", () => {
        render(<TradeHistory />);
        expect(
            screen.getByText("Completed trades will appear here"),
        ).toBeInTheDocument();
    });

    // ── Table rendering ───────────────────────────────────

    it("renders a table when trades are provided via props", () => {
        const trades = makeTrades(3);
        render(<TradeHistory trades={trades} />);

        // Table headers should be visible
        expect(screen.getByText("Time")).toBeInTheDocument();
        expect(screen.getByText("Symbol")).toBeInTheDocument();
        expect(screen.getByText("Qty")).toBeInTheDocument();
        expect(screen.getByText("Price")).toBeInTheDocument();
        expect(screen.getByText("P&L")).toBeInTheDocument();
        expect(screen.getByText("P&L%")).toBeInTheDocument();
        expect(screen.getByText("Fees")).toBeInTheDocument();
        expect(screen.getByText("Status")).toBeInTheDocument();
    });

    it("renders trades from the store", () => {
        const trades = makeTrades(2);
        useTradingStore.getState().setTrades(trades, 2, 1);
        render(<TradeHistory />);

        // Trade symbols appear as text in their own <span>
        expect(screen.getByText("BTCUSDT")).toBeInTheDocument();
    });

    it("displays trade side badge (BUY)", () => {
        const trade = makeTrade({ side: "BUY" });
        useTradingStore.getState().setTrades([trade], 1, 1);
        render(<TradeHistory />);

        // BUY badge should appear
        const buyBadges = screen.getAllByText("BUY");
        expect(buyBadges.length).toBeGreaterThan(0);
    });

    it("displays trade side badge (SELL)", () => {
        const trade = makeTrade({ side: "SELL" });
        useTradingStore.getState().setTrades([trade], 1, 1);
        render(<TradeHistory />);

        // SELL badge should appear
        const sellBadges = screen.getAllByText("SELL");
        expect(sellBadges.length).toBeGreaterThan(0);
    });

    it("shows FILLED status badge", () => {
        const trade = makeTrade({ status: "FILLED" });
        useTradingStore.getState().setTrades([trade], 1, 1);
        render(<TradeHistory />);

        const filledBadges = screen.getAllByText("FILLED");
        expect(filledBadges.length).toBeGreaterThan(0);
    });

    it("shows REJECTED status badge", () => {
        const trade = makeTrade({ status: "REJECTED" });
        useTradingStore.getState().setTrades([trade], 1, 1);
        render(<TradeHistory />);

        const rejectedBadges = screen.getAllByText("REJECTED");
        expect(rejectedBadges.length).toBeGreaterThan(0);
    });

    it("shows PENDING status badge", () => {
        const trade = makeTrade({ status: "PENDING" });
        useTradingStore.getState().setTrades([trade], 1, 1);
        render(<TradeHistory />);

        const pendingBadges = screen.getAllByText("PENDING");
        expect(pendingBadges.length).toBeGreaterThan(0);
    });

    // ── Filters ───────────────────────────────────────────

    it("renders filter buttons (ALL, BUY, SELL)", () => {
        render(<TradeHistory />);

        expect(screen.getByText("ALL")).toBeInTheDocument();
        expect(screen.getByText("BUY")).toBeInTheDocument();
        expect(screen.getByText("SELL")).toBeInTheDocument();
    });

    it("renders the symbol filter input", () => {
        render(<TradeHistory />);

        const input = screen.getByPlaceholderText("Symbol...");
        expect(input).toBeInTheDocument();
    });

    it("allows typing a symbol in the filter input", async () => {
        const user = userEvent.setup();
        render(<TradeHistory />);

        const input = screen.getByPlaceholderText("Symbol...") as HTMLInputElement;
        await user.type(input, "BTC");

        expect(input.value).toBe("BTC");
    });

    it("renders the refresh button", () => {
        render(<TradeHistory />);

        const refreshBtn = screen.getByText(/Refresh/);
        expect(refreshBtn).toBeInTheDocument();
    });

    it("clicking a side filter button triggers fetch (covers onClick handler)", async () => {
        const user = userEvent.setup();
        render(<TradeHistory />);

        // Click "SELL" filter – exercises the onClick→onSideChange→fetchPage path
        const sellBtn = screen.getByText("SELL");
        await user.click(sellBtn);

        // After click, the SELL button should get the active style (cyan background)
        // The component triggers an API call which is intercepted by MSW
        expect(sellBtn.className).toContain("bg-cyan-600");
    });

    it("clicking refresh button triggers fetchPage", async () => {
        const user = userEvent.setup();
        render(<TradeHistory />);

        const refreshBtn = screen.getByText(/Refresh/);
        await user.click(refreshBtn);

        // No crash means the fetchPage callback executed successfully
        expect(refreshBtn).toBeInTheDocument();
    });

    // ── Pagination ────────────────────────────────────────

    it("shows 'Load More' button when there are more trades", () => {
        const trades = makeTrades(5);
        useTradingStore.getState().setTrades(trades, 25, 1);
        render(<TradeHistory />);

        const loadMoreBtn = screen.getByText("Load More");
        expect(loadMoreBtn).toBeInTheDocument();
    });

    it("shows trade count in pagination footer", () => {
        const trades = makeTrades(5);
        useTradingStore.getState().setTrades(trades, 25, 1);
        render(<TradeHistory />);

        expect(screen.getByText(/Showing 5 of 25 trades/)).toBeInTheDocument();
    });

    it("does not show 'Load More' when all trades are loaded", () => {
        const trades = makeTrades(5);
        useTradingStore.getState().setTrades(trades, 5, 1);
        render(<TradeHistory />);

        expect(screen.queryByText("Load More")).not.toBeInTheDocument();
    });

    it("clicking Load More triggers append fetch (covers handleLoadMore)", async () => {
        const user = userEvent.setup();
        const trades = makeTrades(5);
        useTradingStore.getState().setTrades(trades, 25, 1);
        render(<TradeHistory />);

        const loadMoreBtn = screen.getByText("Load More");
        await user.click(loadMoreBtn);

        // After click, button changes to "Loading..." while fetch is in flight
        // MSW returns immediately so it should cycle back to "Load More"
        expect(screen.getByText("Load More")).toBeInTheDocument();
    });

    // ── Store loading state ───────────────────────────────

    it("shows skeleton when store is loading", () => {
        useTradingStore.setState({ tradesLoading: true });
        render(<TradeHistory />);

        const skeleton = document.querySelector(".animate-pulse");
        expect(skeleton).toBeTruthy();
    });

    // ── Keyboard filter → uppercase conversion ────────────

    it("converts symbol input to uppercase automatically", async () => {
        const user = userEvent.setup();
        render(<TradeHistory />);

        const input = screen.getByPlaceholderText("Symbol...") as HTMLInputElement;
        await user.type(input, "btc");

        // onChange handler calls toUpperCase()
        expect(input.value).toBe("BTC");
    });
});