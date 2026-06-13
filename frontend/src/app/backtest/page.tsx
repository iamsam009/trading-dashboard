"use client";

import React, { useState, useCallback, useEffect, useRef } from "react";
import { toast, Toaster } from "react-hot-toast";
import { format, subDays } from "date-fns";

// ─── Types ───────────────────────────────────────────────

interface Strategy {
    id: number;
    name: string;
    description: string | null;
    json_definition: {
        symbols: string[];
        [key: string]: unknown;
    };
    is_active: boolean;
    version: number;
    backtest_results?: BacktestResultData | null;
}

interface BacktestMetrics {
    total_return_pct: number;
    total_pnl: number;
    max_drawdown_pct: number;
    sharpe_ratio: number;
    win_rate_pct: number;
    profit_factor: number;
    total_trades: number;
    winning_trades: number;
    losing_trades: number;
    avg_win: number;
    avg_loss: number;
    best_trade: number;
    worst_trade: number;
}

interface EquityPoint {
    ts: string;
    equity: number;
}

interface Trade {
    entry_time: string;
    exit_time: string;
    side: string;
    entry_price: number;
    exit_price: number;
    pnl: number;
    pnl_pct: number;
}

interface BacktestResultData {
    task_id: string;
    status: string;
    metrics: BacktestMetrics | null;
    equity_curve: EquityPoint[];
    trades: Trade[];
}

interface SubmitResponse {
    task_id: string;
    status: string;
    strategy_id: number;
    symbol: string;
}

// ─── API Client ──────────────────────────────────────────

import api from "@/lib/api";

// ─── Helpers ─────────────────────────────────────────────

function fmtCurrency(v: number): string {
    return new Intl.NumberFormat("en-IN", {
        style: "currency",
        currency: "INR",
        minimumFractionDigits: 2,
    }).format(v);
}

function fmtPct(v: number): string {
    return `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
}

function fmtRatio(v: number): string {
    return v.toFixed(2);
}

// ─── Navbar ──────────────────────────────────────────────

function Navbar() {
    return (
        <nav className="border-b border-slate-700 bg-slate-900 px-6 py-3 flex items-center justify-between">
            <div className="flex items-center gap-3">
                <span className="text-xl font-bold text-white tracking-tight">
                    ⚡ Trading Dashboard
                </span>
            </div>
            <div className="flex items-center gap-4 text-sm text-slate-300">
                <a href="/strategies" className="hover:text-white transition">
                    Strategies
                </a>
                <a href="/backtest" className="text-white font-semibold transition">
                    Backtest
                </a>
            </div>
        </nav>
    );
}

// ─── Equity Curve Chart ──────────────────────────────────

function EquityCurveChart({ data }: { data: EquityPoint[] }) {
    const containerRef = useRef<HTMLDivElement>(null);
    const chartRef = useRef<{ remove: () => void } | null>(null);

    useEffect(() => {
        if (!containerRef.current || data.length === 0) return;

        let cleanup: (() => void) | null = null;

        const initChart = async () => {
            const { createChart, ColorType } = await import("lightweight-charts");

            const chart = createChart(containerRef.current!, {
                width: containerRef.current!.clientWidth,
                height: 400,
                layout: {
                    background: { type: ColorType.Solid, color: "#0f172a" },
                    textColor: "#94a3b8",
                },
                grid: {
                    vertLines: { color: "#1e293b" },
                    horzLines: { color: "#1e293b" },
                },
                crosshair: {
                    mode: 0,
                },
                timeScale: {
                    borderColor: "#334155",
                    timeVisible: true,
                },
                rightPriceScale: {
                    borderColor: "#334155",
                },
            });

            const lineSeries = chart.addLineSeries({
                color: "#22d3ee",
                lineWidth: 2,
                priceFormat: {
                    type: "price",
                    precision: 2,
                    minMove: 0.01,
                },
            });

            const chartData = data.map((point) => ({
                time: point.ts,
                value: point.equity,
            }));

            lineSeries.setData(chartData);
            chart.timeScale().fitContent();

            chartRef.current = chart;

            const handleResize = () => {
                if (containerRef.current) {
                    chart.applyOptions({ width: containerRef.current.clientWidth });
                }
            };
            window.addEventListener("resize", handleResize);

            cleanup = () => {
                window.removeEventListener("resize", handleResize);
                chart.remove();
            };
        };

        initChart();

        return () => {
            cleanup?.();
        };
    }, [data]);

    return (
        <div
            ref={containerRef}
            className="w-full rounded-lg overflow-hidden border border-slate-700"
        />
    );
}

// ─── Metrics Table ───────────────────────────────────────

function MetricsTable({ metrics }: { metrics: BacktestMetrics }) {
    const rows: [string, string, string][] = [
        ["Total Return", fmtPct(metrics.total_return_pct), "text-cyan-400"],
        ["Total P&L", fmtCurrency(metrics.total_pnl), "text-white"],
        ["Max Drawdown", fmtPct(metrics.max_drawdown_pct), "text-red-400"],
        ["Sharpe Ratio", fmtRatio(metrics.sharpe_ratio), "text-yellow-400"],
        ["Win Rate", fmtPct(metrics.win_rate_pct), "text-emerald-400"],
        ["Profit Factor", fmtRatio(metrics.profit_factor), "text-emerald-400"],
        ["Total Trades", String(metrics.total_trades), "text-white"],
        ["Winning Trades", String(metrics.winning_trades), "text-emerald-400"],
        ["Losing Trades", String(metrics.losing_trades), "text-red-400"],
        ["Avg Win", fmtCurrency(metrics.avg_win), "text-emerald-400"],
        ["Avg Loss", fmtCurrency(metrics.avg_loss), "text-red-400"],
        ["Best Trade", fmtCurrency(metrics.best_trade), "text-emerald-400"],
        ["Worst Trade", fmtCurrency(metrics.worst_trade), "text-red-400"],
    ];

    return (
        <div className="overflow-x-auto rounded-lg border border-slate-700">
            <table className="w-full text-sm">
                <thead>
                    <tr className="bg-slate-800 text-slate-400 text-xs uppercase tracking-wider">
                        <th className="text-left px-4 py-3">Metric</th>
                        <th className="text-right px-4 py-3">Value</th>
                    </tr>
                </thead>
                <tbody className="divide-y divide-slate-700">
                    {rows.map(([label, value, colorClass]) => (
                        <tr
                            key={label}
                            className="bg-slate-900 hover:bg-slate-800/50 transition"
                        >
                            <td className="px-4 py-2.5 text-slate-300">{label}</td>
                            <td className={`px-4 py-2.5 text-right font-mono font-semibold ${colorClass}`}>
                                {value}
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
}

// ─── Trades Table ────────────────────────────────────────

function TradesTable({ trades }: { trades: Trade[] }) {
    return (
        <div className="overflow-x-auto rounded-lg border border-slate-700 max-h-80 overflow-y-auto">
            <table className="w-full text-sm">
                <thead className="sticky top-0 bg-slate-800 text-slate-400 text-xs uppercase tracking-wider">
                    <tr>
                        <th className="text-left px-3 py-2">Entry</th>
                        <th className="text-left px-3 py-2">Exit</th>
                        <th className="text-center px-3 py-2">Side</th>
                        <th className="text-right px-3 py-2">Entry Price</th>
                        <th className="text-right px-3 py-2">Exit Price</th>
                        <th className="text-right px-3 py-2">P&L</th>
                        <th className="text-right px-3 py-2">P&L %</th>
                    </tr>
                </thead>
                <tbody className="divide-y divide-slate-700">
                    {trades.map((trade, i) => (
                        <tr
                            key={i}
                            className="bg-slate-900 hover:bg-slate-800/50 transition"
                        >
                            <td className="px-3 py-2 text-slate-400 font-mono text-xs">
                                {format(new Date(trade.entry_time), "dd/MM HH:mm")}
                            </td>
                            <td className="px-3 py-2 text-slate-400 font-mono text-xs">
                                {format(new Date(trade.exit_time), "dd/MM HH:mm")}
                            </td>
                            <td className="px-3 py-2 text-center">
                                <span
                                    className={`text-xs font-semibold px-2 py-0.5 rounded ${trade.side === "LONG"
                                        ? "text-emerald-400 bg-emerald-400/10"
                                        : "text-red-400 bg-red-400/10"
                                        }`}
                                >
                                    {trade.side}
                                </span>
                            </td>
                            <td className="px-3 py-2 text-right font-mono text-slate-300">
                                {trade.entry_price.toFixed(2)}
                            </td>
                            <td className="px-3 py-2 text-right font-mono text-slate-300">
                                {trade.exit_price.toFixed(2)}
                            </td>
                            <td
                                className={`px-3 py-2 text-right font-mono font-semibold ${trade.pnl >= 0 ? "text-emerald-400" : "text-red-400"
                                    }`}
                            >
                                {fmtCurrency(trade.pnl)}
                            </td>
                            <td
                                className={`px-3 py-2 text-right font-mono font-semibold ${trade.pnl_pct >= 0 ? "text-emerald-400" : "text-red-400"
                                    }`}
                            >
                                {fmtPct(trade.pnl_pct)}
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
}

// ─── Main Page ───────────────────────────────────────────

export default function BacktestPage() {
    const [strategies, setStrategies] = useState<Strategy[]>([]);
    const [loadingStrategies, setLoadingStrategies] = useState(true);
    const [selectedStrategy, setSelectedStrategy] = useState<Strategy | null>(null);
    const [symbol, setSymbol] = useState("");
    const [startDate, setStartDate] = useState(
        format(subDays(new Date(), 30), "yyyy-MM-dd")
    );
    const [endDate, setEndDate] = useState(format(new Date(), "yyyy-MM-dd"));
    const [running, setRunning] = useState(false);
    const [polling, setPolling] = useState(false);
    const [taskId, setTaskId] = useState<string | null>(null);
    const [result, setResult] = useState<BacktestResultData | null>(null);
    const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

    // Fetch strategies
    const fetchStrategies = useCallback(async () => {
        try {
            const res = await api.get<Strategy[]>("/strategies/");
            setStrategies(res.data);
        } catch {
            // Interceptor handles toast
        } finally {
            setLoadingStrategies(false);
        }
    }, []);

    useEffect(() => {
        fetchStrategies();
    }, [fetchStrategies]);

    // Clear polling on unmount
    useEffect(() => {
        return () => {
            if (pollRef.current) clearInterval(pollRef.current);
        };
    }, []);

    const handleStrategySelect = (s: Strategy) => {
        setSelectedStrategy(s);
        setResult(null);
        setTaskId(null);
        // Default symbol from the strategy's symbol list
        if (s.json_definition.symbols && s.json_definition.symbols.length > 0) {
            setSymbol(s.json_definition.symbols[0]);
        }
    };

    const handleRunBacktest = async () => {
        if (!selectedStrategy) return;
        if (!symbol.trim()) {
            toast.error("Please enter a symbol");
            return;
        }

        setRunning(true);
        setResult(null);
        setTaskId(null);

        try {
            const res = await api.post<SubmitResponse>("/backtest/", {
                strategy_id: selectedStrategy.id,
                symbol: symbol.trim().toUpperCase(),
                start_date: startDate,
                end_date: endDate,
                initial_capital: 10000,
            });

            setTaskId(res.data.task_id);
            toast.success("Backtest submitted! Polling for results...");
            startPolling(res.data.task_id);
        } catch {
            setRunning(false);
        }
    };

    const startPolling = (tid: string) => {
        setPolling(true);
        if (pollRef.current) clearInterval(pollRef.current);

        pollRef.current = setInterval(async () => {
            try {
                const res = await api.get<BacktestResultData>(
                    `/backtest/${tid}/result`
                );
                const data = res.data;

                if (data.status === "completed") {
                    setResult(data);
                    setRunning(false);
                    setPolling(false);
                    if (pollRef.current) {
                        clearInterval(pollRef.current);
                        pollRef.current = null;
                    }
                    toast.success("Backtest completed!");
                } else if (data.status === "pending" || data.status === "running") {
                    // Still waiting – update progress info
                    if (data.status === "running") {
                        toast("Backtest in progress...", { icon: "⏳" });
                    }
                }
            } catch {
                // Error polling – stop
                setRunning(false);
                setPolling(false);
                if (pollRef.current) {
                    clearInterval(pollRef.current);
                    pollRef.current = null;
                }
            }
        }, 3000);
    };

    return (
        <div className="min-h-screen bg-slate-950 text-white">
            <Toaster
                position="top-right"
                toastOptions={{
                    style: {
                        background: "#1e293b",
                        color: "#f1f5f9",
                        border: "1px solid #334155",
                    },
                }}
            />
            <Navbar />

            <main className="max-w-6xl mx-auto px-4 py-8">
                <h1 className="text-2xl font-bold mb-6">Strategy Backtesting</h1>

                {/* ── Controls ─────────────────────────────── */}
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6 p-6 bg-slate-900 rounded-lg border border-slate-700">
                    {/* Strategy selector */}
                    <div>
                        <label className="block text-xs font-semibold text-slate-400 mb-1 uppercase tracking-wider">
                            Strategy
                        </label>
                        <select
                            className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white focus:ring-2 focus:ring-cyan-500 focus:border-transparent outline-none"
                            value={selectedStrategy?.id ?? ""}
                            onChange={(e) => {
                                const s = strategies.find(
                                    (st) => st.id === Number(e.target.value)
                                );
                                if (s) handleStrategySelect(s);
                            }}
                            disabled={loadingStrategies}
                        >
                            <option value="">
                                {loadingStrategies ? "Loading..." : "Select a strategy"}
                            </option>
                            {strategies.map((s) => (
                                <option key={s.id} value={s.id}>
                                    {s.name}
                                    {s.is_active ? " (active)" : " (inactive)"}
                                </option>
                            ))}
                        </select>
                    </div>

                    {/* Symbol */}
                    <div>
                        <label className="block text-xs font-semibold text-slate-400 mb-1 uppercase tracking-wider">
                            Symbol
                        </label>
                        <input
                            type="text"
                            className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white font-mono focus:ring-2 focus:ring-cyan-500 focus:border-transparent outline-none"
                            value={symbol}
                            onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                            placeholder="e.g. BTCINR"
                        />
                    </div>

                    {/* Start date */}
                    <div>
                        <label className="block text-xs font-semibold text-slate-400 mb-1 uppercase tracking-wider">
                            Start Date
                        </label>
                        <input
                            type="date"
                            className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white focus:ring-2 focus:ring-cyan-500 focus:border-transparent outline-none"
                            value={startDate}
                            onChange={(e) => setStartDate(e.target.value)}
                        />
                    </div>

                    {/* End date */}
                    <div>
                        <label className="block text-xs font-semibold text-slate-400 mb-1 uppercase tracking-wider">
                            End Date
                        </label>
                        <input
                            type="date"
                            className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white focus:ring-2 focus:ring-cyan-500 focus:border-transparent outline-none"
                            value={endDate}
                            onChange={(e) => setEndDate(e.target.value)}
                        />
                    </div>
                </div>

                {/* Run button */}
                <div className="flex items-center gap-3 mb-8">
                    <button
                        onClick={handleRunBacktest}
                        disabled={running || !selectedStrategy}
                        className={`px-6 py-2.5 rounded-lg font-semibold text-sm transition-all flex items-center gap-2 ${running || !selectedStrategy
                            ? "bg-slate-700 text-slate-500 cursor-not-allowed"
                            : "bg-cyan-600 hover:bg-cyan-500 text-white shadow-lg shadow-cyan-500/20"
                            }`}
                    >
                        {running ? (
                            <>
                                <svg
                                    className="animate-spin h-4 w-4"
                                    viewBox="0 0 24 24"
                                    fill="none"
                                >
                                    <circle
                                        className="opacity-25"
                                        cx="12"
                                        cy="12"
                                        r="10"
                                        stroke="currentColor"
                                        strokeWidth="4"
                                    />
                                    <path
                                        className="opacity-75"
                                        fill="currentColor"
                                        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                                    />
                                </svg>
                                {polling ? "Polling..." : "Running..."}
                            </>
                        ) : (
                            "▶ Run Backtest"
                        )}
                    </button>
                    {taskId && (
                        <span className="text-xs text-slate-500 font-mono">
                            Task: {taskId}
                        </span>
                    )}
                </div>

                {/* ── Results ──────────────────────────────── */}
                {result && result.metrics && (
                    <div className="space-y-6">
                        {/* Equity Curve */}
                        <div>
                            <h2 className="text-lg font-semibold mb-3 text-slate-200">
                                Equity Curve
                            </h2>
                            <EquityCurveChart data={result.equity_curve} />
                        </div>

                        {/* Metrics */}
                        <div>
                            <h2 className="text-lg font-semibold mb-3 text-slate-200">
                                Performance Metrics
                            </h2>
                            <MetricsTable metrics={result.metrics} />
                        </div>

                        {/* Trades */}
                        {result.trades.length > 0 && (
                            <div>
                                <h2 className="text-lg font-semibold mb-3 text-slate-200">
                                    Trades ({result.trades.length})
                                </h2>
                                <TradesTable trades={result.trades} />
                            </div>
                        )}
                    </div>
                )}

                {/* Empty state */}
                {!result && !running && (
                    <div className="text-center py-20 text-slate-500">
                        <p className="text-lg">
                            Select a strategy, pick a date range, and run a backtest.
                        </p>
                        <p className="text-sm mt-2">
                            Results will appear here with an equity curve and metrics.
                        </p>
                    </div>
                )}
            </main>
        </div>
    );
}