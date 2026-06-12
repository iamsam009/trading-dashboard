"use client";

import React from "react";
import { useTradingStore, type Position } from "@/store/useTradingStore";

// ── Helpers ─────────────────────────────────────────────────

function fmtCurrency(v: number): string {
    return new Intl.NumberFormat("en-IN", {
        style: "currency",
        currency: "INR",
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    }).format(v);
}

function fmtPct(v: number): string {
    return `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
}

// ── Skeleton ─────────────────────────────────────────────────

export function PositionsTableSkeleton() {
    return (
        <div className="bg-slate-900 border border-slate-700 rounded-xl overflow-hidden animate-pulse">
            <div className="h-10 bg-slate-800" />
            {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="h-14 border-t border-slate-700 flex items-center px-4">
                    <div className="h-3 w-20 bg-slate-700 rounded" />
                </div>
            ))}
        </div>
    );
}

// ── Empty State ──────────────────────────────────────────────

function EmptyState() {
    return (
        <div className="bg-slate-900 border border-slate-700 rounded-xl p-12 text-center">
            <div className="text-3xl mb-2">📭</div>
            <p className="text-slate-400 text-sm">No open positions</p>
            <p className="text-slate-600 text-xs mt-1">
                Positions will appear here once you start trading
            </p>
        </div>
    );
}

// ── Position Row ─────────────────────────────────────────────

function PositionRow({ position }: { position: Position }) {
    const isProfitable = position.unrealized_pnl >= 0;
    const pnlColor = isProfitable ? "text-emerald-400" : "text-red-400";
    const sideColor =
        position.side === "LONG" ? "text-emerald-400 bg-emerald-400/10" : "text-red-400 bg-red-400/10";

    return (
        <tr className="bg-slate-900 hover:bg-slate-800/50 transition border-t border-slate-700/50">
            {/* Symbol & Side */}
            <td className="px-4 py-3">
                <div className="flex items-center gap-2">
                    <span className="font-mono text-sm font-semibold text-white">
                        {position.symbol}
                    </span>
                    <span
                        className={`text-xs font-semibold px-1.5 py-0.5 rounded ${sideColor}`}
                    >
                        {position.side}
                    </span>
                    <span className="text-xs text-slate-500">{position.leverage}x</span>
                </div>
            </td>

            {/* Quantity */}
            <td className="px-4 py-3 text-right font-mono text-sm text-slate-300">
                {position.quantity}
            </td>

            {/* Entry Price */}
            <td className="px-4 py-3 text-right font-mono text-sm text-slate-300">
                {position.entry_price.toFixed(2)}
            </td>

            {/* Mark / Current Price */}
            <td className="px-4 py-3 text-right font-mono text-sm text-white">
                {(position.current_price ?? position.mark_price ?? position.entry_price).toFixed(2)}
            </td>

            {/* Unrealized P&L */}
            <td className={`px-4 py-3 text-right font-mono text-sm font-semibold ${pnlColor}`}>
                {fmtCurrency(position.unrealized_pnl)}
            </td>

            {/* P&L % */}
            <td className={`px-4 py-3 text-right font-mono text-sm font-semibold ${pnlColor}`}>
                {fmtPct(position.unrealized_pnl_percent)}
            </td>

            {/* Margin Used */}
            <td className="px-4 py-3 text-right font-mono text-xs text-slate-400">
                {fmtCurrency(position.margin_used)}
            </td>

            {/* Liquidation Price */}
            <td className="px-4 py-3 text-right font-mono text-xs text-slate-500">
                {position.liquidation_price != null
                    ? position.liquidation_price.toFixed(2)
                    : "—"}
            </td>
        </tr>
    );
}

// ── Main Component ──────────────────────────────────────────

interface PositionsTableProps {
    positions?: Position[];
    isLoading?: boolean;
}

export default function PositionsTable({
    positions: propPositions,
    isLoading: propLoading,
}: PositionsTableProps) {
    const storePositions = useTradingStore((s) => s.positions);
    const storeLoading = useTradingStore((s) => s.positionsLoading);

    const positions = propPositions ?? storePositions;
    const isLoading = propLoading ?? storeLoading;

    if (isLoading) {
        return <PositionsTableSkeleton />;
    }

    if (positions.length === 0) {
        return <EmptyState />;
    }

    return (
        <div className="bg-slate-900 border border-slate-700 rounded-xl overflow-hidden">
            <div className="overflow-x-auto">
                <table className="w-full text-sm">
                    <thead>
                        <tr className="bg-slate-800 text-slate-400 text-xs uppercase tracking-wider">
                            <th className="text-left px-4 py-3">Position</th>
                            <th className="text-right px-4 py-3">Qty</th>
                            <th className="text-right px-4 py-3">Entry</th>
                            <th className="text-right px-4 py-3">Mark</th>
                            <th className="text-right px-4 py-3">PNL</th>
                            <th className="text-right px-4 py-3">PNL%</th>
                            <th className="text-right px-4 py-3">Margin</th>
                            <th className="text-right px-4 py-3">Liq.</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-700/50">
                        {positions.map((p) => (
                            <PositionRow key={p.id} position={p} />
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
}