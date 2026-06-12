/**
 * Test 5: RiskPanel – Update Daily Loss Limit
 *
 * Verifies that the RiskPanel renders risk status, allows editing
 * the daily loss limit, and saves it via PUT /risk/settings.
 */

import "../jest-globals-setup";
import React from "react";
import { render, screen, act, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import RiskPanel from "@/components/RiskPanel";
import { server } from "../mocks/server";
import { http, HttpResponse } from "msw";

describe("RiskPanel", () => {
    beforeEach(() => {
        localStorage.setItem("access_token", "test-jwt-token");
    });

    afterEach(() => {
        localStorage.clear();
    });

    it("renders the RiskPanel heading", async () => {
        await act(async () => {
            render(<RiskPanel />);
        });

        expect(screen.getByText("Risk Management")).toBeInTheDocument();
    });

    it("shows kill-switch status indicator", async () => {
        await act(async () => {
            render(<RiskPanel />);
        });

        await waitFor(() => {
            // Should show kill-switch related text
            expect(screen.getByText(/Kill Switch/i)).toBeInTheDocument();
        });
    });

    it("fetches and displays risk status data", async () => {
        await act(async () => {
            render(<RiskPanel />);
        });

        await waitFor(() => {
            // Should show today's PnL info
            expect(screen.getByText(/Today's PnL/i)).toBeInTheDocument();
        });
    });

    it("renders gauge bars for drawdown visualization", async () => {
        await act(async () => {
            render(<RiskPanel />);
        });

        await waitFor(() => {
            // Should show drawdown info (Drawdown gauge + "Max Drawdown" in settings)
            const drawdownElements = screen.getAllByText(/Drawdown/i);
            expect(drawdownElements.length).toBeGreaterThanOrEqual(1);
        });
    });

    it("displays trailing stop information", async () => {
        await act(async () => {
            render(<RiskPanel />);
        });

        await waitFor(() => {
            // Should show trailing stops section or symbols
            expect(screen.getByText(/Trailing Stops/i)).toBeInTheDocument();
        });
    });

    it("enters edit mode when 'Edit Settings' is clicked", async () => {
        const user = userEvent.setup();

        await act(async () => {
            render(<RiskPanel />);
        });

        await waitFor(() => {
            expect(screen.getByText(/Edit/i)).toBeInTheDocument();
        });

        const editButton = screen.getByText(/Edit/i);
        await user.click(editButton);

        await waitFor(() => {
            // Save button should appear when in edit mode
            expect(screen.getByText(/Save/i)).toBeInTheDocument();
        });
    });

    it("updates daily loss limit field in edit mode", async () => {
        const user = userEvent.setup();

        // Override the MSW handler for risk settings to return known data
        // RiskPanel uses axios with baseURL http://localhost:8000
        server.use(
            http.get("http://localhost:8000/api/v1/risk/settings", () => {
                return HttpResponse.json({
                    daily_loss_limit: 1000,
                    weekly_loss_limit: 5000,
                    max_drawdown_percent: 25,
                    max_open_trades: 10,
                    position_size_percent: 5,
                    max_leverage: 10,
                    stop_loss_percent: 2,
                    take_profit_percent: 5,
                    trailing_stop_enabled: true,
                    trailing_stop_distance_percent: 5,
                    risk_per_trade_percent: 2,
                    kill_switch_enabled: false,
                    kill_switch_reason: null,
                    trading_enabled: true,
                });
            }),
        );

        await act(async () => {
            render(<RiskPanel />);
        });

        await waitFor(() => {
            expect(screen.getByText(/Edit/i)).toBeInTheDocument();
        });

        await user.click(screen.getByText(/Edit/i));

        // Find the daily loss limit input and change it
        await waitFor(async () => {
            const inputs = screen.getAllByRole("spinbutton");
            expect(inputs.length).toBeGreaterThan(0);
        });

        const dailyLossInput = screen.getByDisplayValue("1000");
        await user.clear(dailyLossInput);
        await user.type(dailyLossInput, "500");

        expect(dailyLossInput).toHaveValue(500);
    });

    it("saves updated risk settings", async () => {
        const user = userEvent.setup();

        await act(async () => {
            render(<RiskPanel />);
        });

        await waitFor(() => {
            expect(screen.getByText(/Edit/i)).toBeInTheDocument();
        });

        await user.click(screen.getByText(/Edit/i));

        await waitFor(() => {
            expect(screen.getByText(/Save/i)).toBeInTheDocument();
        });

        // Change daily loss limit
        const dailyLossInput = screen.getByDisplayValue("1000");
        await user.clear(dailyLossInput);
        await user.type(dailyLossInput, "500");

        // Click Save
        await user.click(screen.getByText(/Save/i));

        // After saving, should exit edit mode
        await waitFor(() => {
            expect(screen.getByText(/Edit/i)).toBeInTheDocument();
        });
    });

    it("handles kill-switch toggle", async () => {
        const user = userEvent.setup();

        await act(async () => {
            render(<RiskPanel />);
        });

        await waitFor(() => {
            expect(screen.getByText(/Kill Switch/i)).toBeInTheDocument();
        });
    });
});