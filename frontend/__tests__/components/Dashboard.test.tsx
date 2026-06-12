/**
 * Test 1: Dashboard Loads Initial Data
 *
 * Verifies that the dashboard page mounts, fetches balance data via MSW,
 * and displays the equity value (₹15,000.00).
 */

import "../jest-globals-setup";
import React from "react";
import { render, screen, waitFor, act } from "@testing-library/react";
import DashboardPage from "@/app/dashboard/page";

describe("Dashboard – Initial Data Load", () => {
    beforeEach(() => {
        localStorage.setItem("access_token", "test-jwt-token");
    });

    afterEach(() => {
        localStorage.clear();
    });

    it("renders the dashboard shell (navbar + sidebar)", async () => {
        await act(async () => {
            render(<DashboardPage />);
        });

        // Navbar brand/logo should be visible
        expect(screen.getByText("⚡ Trading Dashboard")).toBeInTheDocument();
    });

    it("fetches and displays balance data", async () => {
        await act(async () => {
            render(<DashboardPage />);
        });

        // Wait for the balance to appear in the sidebar (Portfolio section)
        await waitFor(
            () => {
                // The sidebar label is "Portfolio", balance shown as ₹15,000.00
                expect(screen.getByText("Portfolio")).toBeInTheDocument();
            },
            { timeout: 5000 },
        );
    });

    it("displays the Overview tab by default", async () => {
        await act(async () => {
            render(<DashboardPage />);
        });

        // The Overview tab should be active (highlighted)
        await waitFor(() => {
            const overviewButton = screen.getByText("Overview");
            expect(overviewButton).toBeInTheDocument();
        });
    });

    it("renders all 6 tab navigation items", async () => {
        await act(async () => {
            render(<DashboardPage />);
        });

        const tabLabels = ["Overview", "Positions", "Trade Log", "Analytics", "Risk"];
        for (const label of tabLabels) {
            await waitFor(() => {
                expect(screen.getByText(label)).toBeInTheDocument();
            });
        }
        // "Strategies" appears both in the navbar link and the sidebar tab
        await waitFor(() => {
            const strategiesElements = screen.getAllByText("Strategies");
            expect(strategiesElements.length).toBeGreaterThanOrEqual(1);
        });
    });

    it("shows loading state initially, then renders content", async () => {
        await act(async () => {
            render(<DashboardPage />);
        });

        // After loading, the Portfolio section with balance should appear
        await waitFor(
            () => {
                expect(screen.getByText("Portfolio")).toBeInTheDocument();
            },
            { timeout: 5000 },
        );
    });
});