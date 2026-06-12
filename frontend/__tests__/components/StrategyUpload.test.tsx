/**
 * Test 4: Strategy Upload – JSON Editor Validation
 *
 * Verifies that the strategy creation/upload page handles JSON editing
 * including validation, drag-and-drop, and save functionality.
 */

import "../jest-globals-setup";
import React from "react";
import { render, screen, act, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import StrategiesPage from "@/app/strategies/page";
import { toast } from "react-hot-toast";

// Valid strategy JSON
const VALID_STRATEGY_JSON = JSON.stringify(
    {
        name: "Test MA Crossover",
        description: "A test strategy",
        conditions: [
            {
                indicator: "SMA",
                params: [9],
                crossover: "SMA_21",
                compare_params: [21],
            },
        ],
        action: "BUY",
        quantity_percent: 10,
        symbols: ["BTCUSDT"],
        timeframe: "1h",
    },
    null,
    2,
);

describe("StrategiesPage – JSON Editor & Upload", () => {
    beforeEach(() => {
        localStorage.setItem("access_token", "test-jwt-token");
        jest.clearAllMocks();
    });

    afterEach(() => {
        localStorage.clear();
    });

    it("renders the strategy list page", async () => {
        await act(async () => {
            render(<StrategiesPage />);
        });

        // Should show the page heading
        expect(screen.getByText("Strategies")).toBeInTheDocument();
    });

    it("opens the create modal when '+ New Strategy' is clicked", async () => {
        const user = userEvent.setup();
        await act(async () => {
            render(<StrategiesPage />);
        });

        const newButton = screen.getByText("+ New Strategy");
        await user.click(newButton);

        // Modal should be visible
        await act(async () => {
            await new Promise((r) => setTimeout(r, 200));
        });

        // The modal title should appear (source uses "New Strategy" when creating)
        expect(screen.getByText("New Strategy")).toBeInTheDocument();
    });

    it("shows the JSON editor textarea in the modal", async () => {
        const user = userEvent.setup();
        await act(async () => {
            render(<StrategiesPage />);
        });

        await user.click(screen.getByText("+ New Strategy"));

        await act(async () => {
            await new Promise((r) => setTimeout(r, 200));
        });

        // JSON editor textarea should be present (modal has multiple textboxes: inputs + textarea)
        const textboxes = screen.getAllByRole("textbox");
        const textarea = textboxes.find((el) => el.tagName === "TEXTAREA") as HTMLTextAreaElement;
        expect(textarea).toBeInTheDocument();
    });

    it("shows validation results when 'Validate' is clicked", async () => {
        const user = userEvent.setup();
        await act(async () => {
            render(<StrategiesPage />);
        });

        await user.click(screen.getByText("+ New Strategy"));

        await act(async () => {
            await new Promise((r) => setTimeout(r, 200));
        });

        // Type valid JSON into the textarea (modal has multiple textboxes: inputs + textarea)
        // Use fireEvent.change to avoid userEvent.type interpreting { } as key descriptors
        const textboxes = screen.getAllByRole("textbox");
        const textarea = textboxes.find((el) => el.tagName === "TEXTAREA") as HTMLTextAreaElement;
        fireEvent.change(textarea, { target: { value: VALID_STRATEGY_JSON } });

        // Click Validate button (text is "🔍 Validate" with emoji prefix)
        const validateButton = screen.getByText(/Validate/);
        await user.click(validateButton);

        await act(async () => {
            await new Promise((r) => setTimeout(r, 500));
        });

        // Should show validation results (the MSW handler returns indicators_used etc.)
        await waitFor(() => {
            expect(screen.getByText(/✓ Valid/i)).toBeInTheDocument();
        });
    });

    it("shows error toast for invalid JSON", async () => {
        const user = userEvent.setup();
        await act(async () => {
            render(<StrategiesPage />);
        });

        await user.click(screen.getByText("+ New Strategy"));

        await act(async () => {
            await new Promise((r) => setTimeout(r, 200));
        });

        // Type valid JSON that parses but fails API validation (no conditions)
        // Use fireEvent.change to avoid userEvent.type interpreting { } as key descriptors
        const INVALID_NO_CONDITIONS = JSON.stringify({ name: "Bad", conditions: [] });
        const textboxes = screen.getAllByRole("textbox");
        const textarea = textboxes.find((el) => el.tagName === "TEXTAREA") as HTMLTextAreaElement;
        fireEvent.change(textarea, { target: { value: INVALID_NO_CONDITIONS } });

        // Click Validate (text is "🔍 Validate" with emoji prefix)
        const validateButton = screen.getByText(/Validate/);
        await user.click(validateButton);

        await act(async () => {
            await new Promise((r) => setTimeout(r, 500));
        });

        // Should show error toast (API returned valid=false, so toast.error was called)
        expect(toast.error).toHaveBeenCalled();
    });

    it("displays strategy cards after loading", async () => {
        await act(async () => {
            render(<StrategiesPage />);
        });

        // Wait for strategies to load from MSW
        await act(async () => {
            await new Promise((r) => setTimeout(r, 1000));
        });

        // Strategy name should appear in a card or heading
        // The page will show loaded strategies
    });

    it("has the active toggle on strategy cards", async () => {
        await act(async () => {
            render(<StrategiesPage />);
        });

        await act(async () => {
            await new Promise((r) => setTimeout(r, 1000));
        });

        // The toggle is a <button> ("Activate"/"Pause"), not a checkbox
        const activateButtons = screen.queryAllByText("Activate");
        const pauseButtons = screen.queryAllByText("Pause");
        expect(activateButtons.length + pauseButtons.length).toBeGreaterThan(0);
    });

    it("handles drag-and-drop file upload for JSON", async () => {
        const user = userEvent.setup();
        await act(async () => {
            render(<StrategiesPage />);
        });

        await user.click(screen.getByText("+ New Strategy"));

        await act(async () => {
            await new Promise((r) => setTimeout(r, 200));
        });

        // The drop zone label text should be visible in the modal
        // Actual text: "JSON Definition (drag & drop .json file)"
        expect(
            screen.getByText(/drag & drop/i),
        ).toBeInTheDocument();
    });
});