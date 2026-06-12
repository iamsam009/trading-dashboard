/**
 * RealTimePrices – displays live price cards for all subscribed symbols.
 *
 * Subscribes to the Zustand dashboardStore for market data updates.
 * Each card shows:
 * - Symbol name
 * - Last price
 * - 24h change (absolute and percentage)
 * - Color-coded green/red based on direction
 */
"use client";

import React, { useMemo } from "react";
import { useDashboardStore } from "@/store/dashboardStore";

// ── Helpers ──────────────────────────────────────────────────────────

function formatPrice(price: number): string {
    if (price >= 1000) {
        return price.toLocaleString("en-IN", { maximumFractionDigits: 2 });
    }
    return price.toFixed(2);
}

function formatChange(change: number): string {
    const sign = change >= 0 ? "+" : "";
    return `${sign}${change.toFixed(2)}%`;
}

// ── Component ────────────────────────────────────────────────────────

export default function RealTimePrices() {
    const marketData = useDashboardStore((s) => s.marketData);
    const subscribedSymbols = useDashboardStore((s) => s.subscribedSymbols);
    const connected = useDashboardStore((s) => s.connected);

    const symbols = useMemo(() => {
        // Use subscribed symbols if available, otherwise fall back to marketData keys
        if (subscribedSymbols.length > 0) return subscribedSymbols;
        return Object.keys(marketData);
    }, [subscribedSymbols, marketData]);

    if (!connected) {
        return (
            <div className="rounded-lg border border-yellow-600/30 bg-yellow-900/20 p-4">
                <p className="text-sm text-yellow-400">
                    ⏳ Connecting to real-time data…
                </p>
            </div>
        );
    }

    if (symbols.length === 0) {
        return (
            <div className="rounded-lg border border-gray-700 bg-gray-800/50 p-6 text-center">
                <p className="text-sm text-gray-400">
                    No active strategies. Create a strategy to see live prices.
                </p>
            </div>
        );
    }

    return (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {symbols.map((symbol) => {
                const data = marketData[symbol];
                if (!data) {
                    return (
                        <div
                            key={symbol}
                            className="rounded-lg border border-gray-700 bg-gray-800/40 p-4"
                        >
                            <h3 className="text-sm font-semibold text-gray-300">
                                {symbol}
                            </h3>
                            <p className="mt-1 text-gray-500">Loading…</p>
                        </div>
                    );
                }

                const isPositive = data.change_percent >= 0;
                const changeColor = isPositive ? "text-green-400" : "text-red-400";
                const bgGlow = isPositive
                    ? "border-green-600/30 bg-green-900/10"
                    : "border-red-600/30 bg-red-900/10";

                return (
                    <div
                        key={symbol}
                        className={`rounded-lg border p-4 transition-colors hover:border-gray-500 ${bgGlow}`}
                    >
                        {/* Symbol */}
                        <h3 className="text-sm font-semibold text-gray-200">
                            {symbol}
                        </h3>

                        {/* Price */}
                        <p className="mt-2 text-2xl font-bold text-white tabular-nums">
                            ₹{formatPrice(data.price)}
                        </p>

                        {/* 24h Change */}
                        <div className="mt-1 flex items-center gap-2">
                            <span className={`text-sm font-medium tabular-nums ${changeColor}`}>
                                {formatChange(data.change_percent)}
                            </span>
                            <span className="text-xs text-gray-500">24h</span>
                        </div>

                        {/* High / Low */}
                        <div className="mt-3 flex justify-between text-xs text-gray-400">
                            <span>
                                H:{" "}
                                <span className="text-gray-300 tabular-nums">
                                    ₹{formatPrice(data.high_24h)}
                                </span>
                            </span>
                            <span>
                                L:{" "}
                                <span className="text-gray-300 tabular-nums">
                                    ₹{formatPrice(data.low_24h)}
                                </span>
                            </span>
                        </div>

                        {/* Volume */}
                        <div className="mt-1 text-xs text-gray-500">
                            Vol: {data.volume_24h.toLocaleString("en-IN")}
                        </div>
                    </div>
                );
            })}
        </div>
    );
}