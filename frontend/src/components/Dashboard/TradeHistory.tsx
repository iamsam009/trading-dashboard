"use client";

import React, { useState, useCallback } from "react";
import { format } from "date-fns";
import { useTradingStore, type TradeRecord } from "@/store/useTradingStore";
import api from "@/lib/api";

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

export function TradeHistorySkeleton() {
    return (
        <div className="bg-slate-900 border border-slate-700 rounded-xl overflow-hidden animate-pulse">
            <div className="h-10 bg-slate-800" />
            {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="h-12 border-t border-slate-700 flex items-center px-4">
                    <div className="h-3 w-32 bg-slate-700 rounded" />
                </div>
            ))}
        </div>
    );
}

// ── Empty State ──────────────────────────────────────────────

function EmptyState() {
    return (
        <div className="bg-slate-900 border border-slate-700 rounded-xl p-12 text-center">
            <div className="text-3xl mb-2">📋</div>
            <p className="text-slate-400 text-sm">No trade history yet</p>
            <p className="text-slate-600 text-xs mt-1">
                Completed trades will appear here
            </p>
        </div>
    );
}

// ── Filters Bar ──────────────────────────────────────────────

type SideFilter = "ALL" | "BUY" | "SELL";

interface FiltersBarProps {
    symbol: string;
    onSymbolChange: (v: string) => void;
    side: SideFilter;
    onSideChange: (v: SideFilter) => void;
    onRefresh: () => void;
}

function FiltersBar({ symbol, onSymbolChange, side, onSideChange, onRefresh }: FiltersBarProps) {
    return (
        <div className="flex flex-wrap items-center gap-3 mb-3">
            <input
                type="text"
                className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-white font-mono placeholder-slate-500 focus:ring-2 focus:ring-cyan-500 focus:border-transparent outline-none w-32"
                placeholder="Symbol..."
                value={symbol}
                onChange={(e) => onSymbolChange(e.target.value.toUpperCase())}
            />
            <div className="flex rounded-lg overflow-hidden border border-slate-600">
                {(["ALL", "BUY", "SELL"] as SideFilter[]).map((s) => (
                    <button
                        key={s}
                        onClick={() => onSideChange(s)}
                        className={`px-3 py-1.5 text-xs font-semibold transition ${side === s
                                ? "bg-cyan-600 text-white"
                                : "bg-slate-800 text-slate-400 hover:bg-slate-700"
                            }`}
                    >
                        {s}
                    </button>
                ))}
            </div>
            <button
                onClick={onRefresh}
                className="px-3 py-1.5 text-xs font-semibold bg-slate-800 border border-slate-600 rounded-lg text-slate-400 hover:bg-slate-700 transition"
            >
                🔄 Refresh
            </button>
        </div>
    );
}

// ── Trade Row ────────────────────────────────────────────────

function TradeRow({ trade }: { trade: TradeRecord }) {
    const pnl = trade.pnl ?? 0;
    const pnlPct = trade.pnl_percent ?? 0;
    const isProfitable = pnl >= 0;
    const pnlColor = isProfitable ? "text-emerald-400" : "text-red-400";
    const sideColor =
        trade.side === "BUY" ? "text-emerald-400 bg-emerald-400/10" : "text-red-400 bg-red-400/10";

    return (
        <tr className="bg-slate-900 hover:bg-slate-800/50 transition border-t border-slate-700/50">
            <td className="px-3 py-2.5 text-slate-400 font-mono text-xs whitespace-nowrap">
                {trade.created_at ? format(new Date(trade.created_at), "dd/MM HH:mm:ss") : "—"}
            </td>
            <td className="px-3 py-2.5">
                <div className="flex items-center gap-1.5">
                    <span className="font-mono text-sm font-semibold text-white">
                        {trade.symbol}
                    </span>
                    <span className={`text-xs font-semibold px-1.5 py-0.5 rounded ${sideColor}`}>
                        {trade.side}
                    </span>
                </div>
            </td>
            <td className="px-3 py-2.5 text-right font-mono text-sm text-slate-300">
                {trade.quantity}
            </td>
            <td className="px-3 py-2.5 text-right font-mono text-sm text-slate-300">
                {trade.price != null ? trade.price.toFixed(2) : "—"}
            </td>
            <td className={`px-3 py-2.5 text-right font-mono text-sm font-semibold ${pnlColor}`}>
                {fmtCurrency(pnl)}
            </td>
            <td className={`px-3 py-2.5 text-right font-mono text-xs font-semibold ${pnlColor}`}>
                {fmtPct(pnlPct)}
            </td>
            <td className="px-3 py-2.5 text-right font-mono text-xs text-slate-500">
                {trade.fees != null ? fmtCurrency(trade.fees) : "—"}
            </td>
            <td className="px-3 py-2.5 text-center">
                <span
                    className={`text-xs font-semibold px-1.5 py-0.5 rounded ${trade.status === "FILLED"
                            ? "text-emerald-400 bg-emerald-400/10"
                            : trade.status === "REJECTED"
                                ? "text-red-400 bg-red-400/10"
                                : "text-slate-400 bg-slate-400/10"
                        }`}
                >
                    {trade.status}
                </span>
            </td>
        </tr>
    );
}

// ── Main Component ──────────────────────────────────────────

interface TradeHistoryProps {
    trades?: TradeRecord[];
    isLoading?: boolean;
}

export default function TradeHistory({
    trades: propTrades,
    isLoading: propLoading,
}: TradeHistoryProps) {
    const storeTrades = useTradingStore((s) => s.trades);
    const storeTotal = useTradingStore((s) => s.tradesTotal);
    const storePage = useTradingStore((s) => s.tradesPage);
    const storeLoading = useTradingStore((s) => s.tradesLoading);
    const setTrades = useTradingStore((s) => s.setTrades);
    const appendTrades = useTradingStore((s) => s.appendTrades);
    const setTradesLoading = useTradingStore((s) => s.setTradesLoading);

    const [symbol, setSymbol] = useState("");
    const [side, setSide] = useState<SideFilter>("ALL");
    const [loadingMore, setLoadingMore] = useState(false);

    const trades = propTrades ?? storeTrades;
    const isLoading = propLoading ?? storeLoading;

    const fetchPage = useCallback(
        async (page: number, append: boolean) => {
            if (append) {
                setLoadingMore(true);
            } else {
                setTradesLoading(true);
            }

            try {
                const params: Record<string, string | number> = { page, size: 20 };
                if (symbol) params.symbol = symbol;
                if (side !== "ALL") params.side = side;

                const res = await api.get<{
                    orders: TradeRecord[];
                    total: number;
                    page: number;
                    size: number;
                }>("/trading/orders", { params });

                if (append) {
                    appendTrades(res.data.orders, res.data.total, page);
                } else {
                    setTrades(res.data.orders, res.data.total, page);
                }
            } catch {
                // Interceptor handles toast
                if (append) setLoadingMore(false);
            } finally {
                setLoadingMore(false);
            }
        },
        [symbol, side, setTrades, appendTrades, setTradesLoading],
    );

    const handleRefresh = useCallback(() => {
        fetchPage(1, false);
    }, [fetchPage]);

    const handleLoadMore = useCallback(() => {
        fetchPage(storePage + 1, true);
    }, [fetchPage, storePage]);

    const hasMore = trades.length < storeTotal;

    return (
        <div>
            <FiltersBar
                symbol={symbol}
                onSymbolChange={setSymbol}
                side={side}
                onSideChange={setSide}
                onRefresh={handleRefresh}
            />

            {isLoading ? (
                <TradeHistorySkeleton />
            ) : trades.length === 0 ? (
                <EmptyState />
            ) : (
                <div className="bg-slate-900 border border-slate-700 rounded-xl overflow-hidden">
                    <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                            <thead>
                                <tr className="bg-slate-800 text-slate-400 text-xs uppercase tracking-wider">
                                    <th className="text-left px-3 py-2.5">Time</th>
                                    <th className="text-left px-3 py-2.5">Symbol</th>
                                    <th className="text-right px-3 py-2.5">Qty</th>
                                    <th className="text-right px-3 py-2.5">Price</th>
                                    <th className="text-right px-3 py-2.5">P&L</th>
                                    <th className="text-right px-3 py-2.5">P&L%</th>
                                    <th className="text-right px-3 py-2.5">Fees</th>
                                    <th className="text-center px-3 py-2.5">Status</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-slate-700/50">
                                {trades.map((t) => (
                                    <TradeRow key={t.id} trade={t} />
                                ))}
                            </tbody>
                        </table>
                    </div>

                    {/* Pagination */}
                    {hasMore && (
                        <div className="border-t border-slate-700 px-4 py-3 flex items-center justify-between">
                            <span className="text-xs text-slate-500">
                                Showing {trades.length} of {storeTotal} trades
                            </span>
                            <button
                                onClick={handleLoadMore}
                                disabled={loadingMore}
                                className="px-4 py-1.5 text-xs font-semibold bg-slate-800 border border-slate-600 rounded-lg text-slate-300 hover:bg-slate-700 transition disabled:opacity-50"
                            >
                                {loadingMore ? "Loading..." : "Load More"}
                            </button>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}