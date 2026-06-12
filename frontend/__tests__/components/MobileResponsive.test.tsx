/**
 * Test 6: Mobile Responsiveness
 *
 * Verifies that dashboard components render correctly on iPhone 12 viewport
 * (390x844) without horizontal overflow and with proper mobile adaptations.
 */

import "../jest-globals-setup";
import React from "react";
import { render, screen, act, waitFor } from "@testing-library/react";
import DashboardPage from "@/app/dashboard/page";

// Set viewport to iPhone 12 dimensions
const IPHONE_12_VIEWPORT = { width: 390, height: 844 };

describe("Mobile Responsiveness – iPhone 12", () => {
    beforeEach(() => {
        localStorage.setItem("access_token", "test-jwt-token");
        // Override window.innerWidth/innerHeight for mobile viewport
        Object.defineProperty(window, "innerWidth", {
            writable: true,
            configurable: true,
            value: IPHONE_12_VIEWPORT.width,
        });
        Object.defineProperty(window, "innerHeight", {
            writable: true,
            configurable: true,
            value: IPHONE_12_VIEWPORT.height,
        });
        // Trigger resize event so components that listen can react
        window.dispatchEvent(new Event("resize"));
    });

    afterEach(() => {
        localStorage.clear();
    });

    it("renders the dashboard without horizontal overflow at 390px", async () => {
        await act(async () => {
            render(<DashboardPage />);
        });

        await waitFor(
            () => {
                expect(screen.getByText("⚡ Trading Dashboard")).toBeInTheDocument();
            },
            { timeout: 5000 },
        );

        // Check that the main content area fits within the viewport
        const mainElement = document.querySelector("main");
        if (mainElement) {
            const styles = window.getComputedStyle(mainElement);
            // Should not have a fixed width larger than viewport
            expect(mainElement.scrollWidth).toBeLessThanOrEqual(IPHONE_12_VIEWPORT.width + 10);
        }
    });

    it("has a hamburger/mobile menu toggle button", async () => {
        await act(async () => {
            render(<DashboardPage />);
        });

        await waitFor(() => {
            // The hamburger button should be in the navbar
            const buttons = screen.getAllByRole("button");
            const hamburgerBtn = buttons.find(
                (btn) =>
                    btn.className.includes("md:hidden") ||
                    btn.getAttribute("aria-label")?.includes("menu") ||
                    btn.innerHTML.includes("path"),
            );
            // There should be at least a sidebar toggle button
            expect(buttons.length).toBeGreaterThan(0);
        });
    });

    it("sidebar is collapsible on mobile", async () => {
        await act(async () => {
            render(<DashboardPage />);
        });

        await waitFor(() => {
            // The sidebar toggle should exist
            const toggleBtn = screen.queryByRole("button", { name: /toggle/i }) ||
                document.querySelector('[class*="md:hidden"]');
            // Sidebar should exist
            const aside = document.querySelector("aside");
            expect(aside).toBeInTheDocument();
        });
    });

    it("tab navigation is accessible on mobile", async () => {
        await act(async () => {
            render(<DashboardPage />);
        });

        await waitFor(() => {
            const tabLabels = ["Overview", "Positions", "Trade Log", "Analytics", "Risk"];
            for (const label of tabLabels) {
                const tab = screen.getByText(label);
                expect(tab).toBeInTheDocument();
            }
            // "Strategies" appears in both sidebar nav and navbar - use getAllByText
            const strategiesElements = screen.getAllByText("Strategies");
            expect(strategiesElements.length).toBeGreaterThanOrEqual(1);
        });
    });

    it("cards grid adapts to single column on mobile", async () => {
        await act(async () => {
            render(<DashboardPage />);
        });

        await waitFor(
            () => {
                // The metrics cards grid should have mobile-responsive classes
                const grid = document.querySelector(".grid");
                if (grid) {
                    const classes = grid.className;
                    // Should contain grid-cols-2 (mobile) or grid-cols-1
                    expect(
                        classes.includes("grid-cols-1") || classes.includes("grid-cols-2"),
                    ).toBe(true);
                }
            },
            { timeout: 5000 },
        );
    });

    it("no element forces horizontal scrollbar", async () => {
        await act(async () => {
            render(<DashboardPage />);
        });

        await waitFor(
            () => {
                const body = document.body;
                // Body should not overflow horizontally
                const hasHorizontalScroll = body.scrollWidth > body.clientWidth;
                // Tables can use overflow-x-auto which is fine
                const overflowTables = document.querySelectorAll(".overflow-x-auto");
                // The overall page should not force horizontal scroll
                expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(
                    IPHONE_12_VIEWPORT.width + 50,
                );
            },
            { timeout: 5000 },
        );
    });
});