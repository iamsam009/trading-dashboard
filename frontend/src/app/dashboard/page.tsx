"use client";

/**
 * Dashboard Page – Main analytics dashboard with tabs.
 *
 * Orchestrates all dashboard sub-components:
 * - MetricsCards, EquityChart, PositionsTable, TradeHistory, StrategyRunner
 * - RealTimePrices (WebSocket-driven), RiskPanel
 * - Tab navigation with URL hash-based routing
 * - Responsive mobile layout with collapsible sidebar
 * - Fetches overview data from GET /api/v1/dashboard/overview
 */

import React, { useEffect, useState, useCallback, useMemo } from "react";
import { Toaster } from "react-hot-toast";
import dynamic from "next/dynamic";

import api from "@/lib/api";
import { useTradingStore } from "@/store/useTradingStore";
import { useWebSocket } from "@/hooks/useWebSocket";

// Lazy-load heavy components
const MetricsCards = dynamic(() => import("@/components/Dashboard/MetricsCards"), {
    loading: () => <MetricsCardsSkeleton />,
});
const EquityChart = dynamic(() => import("@/components/Dashboard/EquityChart"), {
    loading: () => <EquityChartSkeleton />,
});
const PositionsTable = dynamic(() => import("@/components/Dashboard/PositionsTable"), {
    loading: () => <PositionsTableSkeleton />,
});
const TradeHistory = dynamic(() => import("@/components/Dashboard/TradeHistory"), {
    loading: () => <TradeHistorySkeleton />,
});
const StrategyRunner = dynamic(() => import("@/components/Strategy/StrategyRunner"), {
    loading: () => <StrategyRunnerSkeleton />,
});
const RealTimePrices = dynamic(() => import("@/components/Dashboard/RealTimePrices"), {
    ssr: false,
});
const RiskPanel = dynamic(() => import("@/components/RiskPanel"), {
    ssr: false,
    loading: () => <RiskPanelSkeleton />,
});

// Import skeletons directly for the loading placeholders
import { MetricsCardsSkeleton } from "@/components/Dashboard/MetricsCards";
import { EquityChartSkeleton } from "@/components/Dashboard/EquityChart";
import { PositionsTableSkeleton } from "@/components/Dashboard/PositionsTable";
import { TradeHistorySkeleton } from "@/components/Dashboard/TradeHistory";
import { StrategyRunnerSkeleton } from "@/components/Strategy/StrategyRunner";

// ── Types ────────────────────────────────────────────────────

type TabId = "overview" | "positions" | "strategies" | "trades" | "analytics" | "risk";

interface TabDef {
    id: TabId;
    label: string;
    icon: string;
}

const TABS: TabDef[] = [
    { id: "overview", label: "Overview", icon: "📊" },
    { id: "positions", label: "Positions", icon: "📈" },
    { id: "strategies", label: "Strategies", icon: "🤖" },
    { id: "trades", label: "Trade Log", icon: "📋" },
    { id: "analytics", label: "Analytics", icon: "📉" },
    { id: "risk", label: "Risk", icon: "🛡️" },
];

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

// ── Skeleton for RiskPanel ───────────────────────────────────

function RiskPanelSkeleton() {
    return (
        <div className="bg-slate-900 border border-slate-700 rounded-xl p-6 animate-pulse">
            <div className="h-4 w-24 bg-slate-700 rounded mb-4" />
            <div className="space-y-3">
                {Array.from({ length: 4 }).map((_, i) => (
                    <div key={i} className="h-10 bg-slate-800 rounded" />
                ))}
            </div>
        </div>
    );
}

// ── Page Skeleton ────────────────────────────────────────────

function DashboardSkeleton() {
    return (
        <div className="space-y-6">
            <MetricsCardsSkeleton />
            <EquityChartSkeleton />
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <PositionsTableSkeleton />
                <StrategyRunnerSkeleton />
            </div>
        </div>
    );
}

// ── Navbar ───────────────────────────────────────────────────

function Navbar({
    activeTab,
    onTabChange,
    sidebarOpen,
    onToggleSidebar,
}: {
    activeTab: TabId;
    onTabChange: (tab: TabId) => void;
    sidebarOpen: boolean;
    onToggleSidebar: () => void;
}) {
    return (
        <nav className="border-b border-slate-700 bg-slate-900 px-4 md:px-6 py-3 flex items-center justify-between">
            <div className="flex items-center gap-3">
                {/* Mobile hamburger */}
                <button
                    onClick={onToggleSidebar}
                    className="md:hidden text-slate-400 hover:text-white transition p-1"
                    aria-label="Toggle sidebar"
                >
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d={sidebarOpen ? "M6 18L18 6M6 6l12 12" : "M4 6h16M4 12h16M4 18h16"}
                        />
                    </svg>
                </button>
                <span className="text-xl font-bold text-white tracking-tight">
                    ⚡ Trading Dashboard
                </span>
            </div>
            <div className="flex items-center gap-4 text-sm text-slate-300">
                <a href="/strategies" className="hover:text-white transition">
                    Strategies
                </a>
                <a href="/backtest" className="hover:text-white transition">
                    Backtest
                </a>
                <a href="/dashboard" className="text-white font-semibold transition">
                    Dashboard
                </a>
            </div>
        </nav>
    );
}

// ── Sidebar ──────────────────────────────────────────────────

function Sidebar({
    activeTab,
    onTabChange,
    sidebarOpen,
    balance,
    connected,
}: {
    activeTab: TabId;
    onTabChange: (tab: TabId) => void;
    sidebarOpen: boolean;
    balance: { total_equity: number; total_unrealized_pnl: number } | null;
    connected: boolean;
}) {
    return (
        <>
            {/* Mobile overlay */}
            {sidebarOpen && (
                <div
                    className="fixed inset-0 bg-black/50 z-20 md:hidden"
                    onClick={() => onTabChange(activeTab)} // closes via parent
                />
            )}

            <aside
                className={`
                    fixed md:sticky top-0 left-0 z-30 h-screen
                    w-64 bg-slate-900 border-r border-slate-700
                    transform transition-transform duration-200
                    ${sidebarOpen ? "translate-x-0" : "-translate-x-full"}
                    md:translate-x-0 md:top-[57px] md:h-[calc(100vh-57px)]
                    flex flex-col
                `}
            >
                {/* Balance Summary */}
                {balance && (
                    <div className="p-4 border-b border-slate-700">
                        <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">
                            Portfolio
                        </div>
                        <div className="text-lg font-bold font-mono text-white">
                            {fmtCurrency(balance.total_equity)}
                        </div>
                        <div
                            className={`text-xs font-mono mt-1 ${balance.total_unrealized_pnl >= 0 ? "text-emerald-400" : "text-red-400"
                                }`}
                        >
                            {fmtPct(balance.total_unrealized_pnl)} unrealized
                        </div>
                    </div>
                )}

                {/* Connection Status */}
                <div className="px-4 py-2 border-b border-slate-700">
                    <div className="flex items-center gap-2">
                        <div
                            className={`w-2 h-2 rounded-full ${connected ? "bg-emerald-400" : "bg-red-400"}`}
                        />
                        <span className="text-xs text-slate-400">
                            {connected ? "Live" : "Disconnected"}
                        </span>
                    </div>
                </div>

                {/* Tab Navigation */}
                <nav className="flex-1 overflow-y-auto p-2">
                    {TABS.map((tab) => (
                        <button
                            key={tab.id}
                            onClick={() => onTabChange(tab.id)}
                            className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition mb-1 ${activeTab === tab.id
                                ? "bg-cyan-600/20 text-cyan-400 font-semibold"
                                : "text-slate-400 hover:bg-slate-800 hover:text-white"
                                }`}
                        >
                            <span className="text-base">{tab.icon}</span>
                            {tab.label}
                        </button>
                    ))}
                </nav>

                {/* Footer */}
                <div className="p-4 border-t border-slate-700">
                    <a
                        href="/strategies"
                        className="block w-full text-center text-xs text-cyan-400 hover:text-cyan-300 transition py-2"
                    >
                        + Create Strategy
                    </a>
                </div>
            </aside>
        </>
    );
}

// ── Tab Content Renderers ────────────────────────────────────

function OverviewTab() {
    const metrics = useTradingStore((s) => s.metrics);
    const dailyPnl = useTradingStore((s) => s.dailyPnl);
    const metricsLoading = useTradingStore((s) => s.metricsLoading);

    return (
        <div className="space-y-6">
            <MetricsCards metrics={metrics} dailyPnl={dailyPnl} isLoading={metricsLoading} />
            <EquityChart
                data={metrics?.equity_curve ?? []}
                isLoading={metricsLoading}
            />
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <PositionsTable />
                <StrategyRunner />
            </div>
        </div>
    );
}

function PositionsTab() {
    return (
        <div className="space-y-6">
            <PositionsTable />
        </div>
    );
}

function StrategiesTab() {
    return (
        <div className="space-y-6">
            <StrategyRunner />
        </div>
    );
}

function TradeLogTab() {
    return (
        <div className="space-y-6">
            <TradeHistory />
        </div>
    );
}

function AnalyticsTab() {
    const metrics = useTradingStore((s) => s.metrics);
    const metricsLoading = useTradingStore((s) => s.metricsLoading);

    return (
        <div className="space-y-6">
            <MetricsCards metrics={metrics} isLoading={metricsLoading} />
            <EquityChart
                data={metrics?.equity_curve ?? []}
                isLoading={metricsLoading}
            />
            {/* Strategy Comparison placeholder */}
            <div className="bg-slate-900 border border-slate-700 rounded-xl p-6">
                <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-4">
                    Strategy Comparison
                </h3>
                <p className="text-sm text-slate-500 text-center py-8">
                    Comparative analytics will be available when multiple strategies have trade history.
                </p>
            </div>
        </div>
    );
}

function RiskTab() {
    return (
        <div className="space-y-6">
            <RiskPanel />
        </div>
    );
}

// ── Main Dashboard Component ─────────────────────────────────

export default function DashboardPage() {
    const [activeTab, setActiveTab] = useState<TabId>("overview");
    const [sidebarOpen, setSidebarOpen] = useState(false);
    const [overviewLoading, setOverviewLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    // Store actions
    const setMetrics = useTradingStore((s) => s.setMetrics);
    const setDailyPnl = useTradingStore((s) => s.setDailyPnl);
    const setPositions = useTradingStore((s) => s.setPositions);
    const setBalance = useTradingStore((s) => s.setBalance);
    const setStrategies = useTradingStore((s) => s.setStrategies);
    const balance = useTradingStore((s) => s.balance);
    const connected = false; // placeholder - will be from WebSocket

    // ── Fetch overview data ───────────────────────────────

    const fetchOverview = useCallback(async () => {
        setOverviewLoading(true);
        setError(null);
        try {
            const res = await api.get("/dashboard/overview");
            const data = res.data;

            // Metrics
            if (data.metrics) {
                setMetrics(data.metrics);
            }
            setDailyPnl(data.daily_pnl ?? 0);

            // Balance
            if (data.balance) {
                setBalance({
                    total_equity: data.balance.total_equity ?? 0,
                    total_used_margin: data.balance.total_used_margin ?? 0,
                    total_available: data.balance.total_available ?? 0,
                    total_unrealized_pnl: data.balance.total_unrealized_pnl ?? 0,
                    balances: data.balance.balances ?? [],
                });
            }

            // Positions
            if (data.positions) {
                setPositions(data.positions);
            }

            // Strategies
            if (data.strategies) {
                setStrategies(data.strategies);
            }
        } catch (err: unknown) {
            const msg =
                err instanceof Error ? err.message : "Failed to load dashboard data";
            setError(msg);
        } finally {
            setOverviewLoading(false);
        }
    }, [setMetrics, setDailyPnl, setBalance, setPositions, setStrategies]);

    // ── Initial load + periodic refresh ──────────────────

    useEffect(() => {
        fetchOverview();

        // Auto-refresh every 30 seconds
        const interval = setInterval(fetchOverview, 30_000);
        return () => clearInterval(interval);
    }, [fetchOverview]);

    // ── Tab handling ─────────────────────────────────────

    const handleTabChange = useCallback((tab: TabId) => {
        setActiveTab(tab);
        setSidebarOpen(false); // close mobile sidebar on tab change
    }, []);

    const toggleSidebar = useCallback(() => {
        setSidebarOpen((prev) => !prev);
    }, []);

    // ── Sidebar balance display ──────────────────────────

    const sidebarBalance = useMemo(() => {
        if (!balance) return null;
        return {
            total_equity: balance.total_equity,
            total_unrealized_pnl: balance.total_unrealized_pnl,
        };
    }, [balance]);

    // ── Render ───────────────────────────────────────────

    const renderTabContent = () => {
        if (overviewLoading) {
            return <DashboardSkeleton />;
        }

        if (error) {
            return (
                <div className="bg-red-900/20 border border-red-600/30 rounded-xl p-8 text-center">
                    <div className="text-3xl mb-2">⚠️</div>
                    <p className="text-red-400 text-sm">{error}</p>
                    <button
                        onClick={fetchOverview}
                        className="mt-4 px-4 py-2 text-xs font-semibold bg-red-600/20 text-red-400 border border-red-600/30 rounded-lg hover:bg-red-600/30 transition"
                    >
                        Retry
                    </button>
                </div>
            );
        }

        switch (activeTab) {
            case "overview":
                return <OverviewTab />;
            case "positions":
                return <PositionsTab />;
            case "strategies":
                return <StrategiesTab />;
            case "trades":
                return <TradeLogTab />;
            case "analytics":
                return <AnalyticsTab />;
            case "risk":
                return <RiskTab />;
            default:
                return <OverviewTab />;
        }
    };

    return (
        <div className="min-h-screen bg-slate-950 text-white">
            <Toaster
                position="top-right"
                toastOptions={{
                    style: {
                        background: "#1e293b",
                        color: "#e2e8f0",
                        border: "1px solid #334155",
                        fontSize: "13px",
                    },
                    success: {
                        iconTheme: { primary: "#22d3ee", secondary: "#1e293b" },
                    },
                    error: {
                        iconTheme: { primary: "#f87171", secondary: "#1e293b" },
                    },
                }}
            />

            <Navbar
                activeTab={activeTab}
                onTabChange={handleTabChange}
                sidebarOpen={sidebarOpen}
                onToggleSidebar={toggleSidebar}
            />

            <div className="flex">
                <Sidebar
                    activeTab={activeTab}
                    onTabChange={handleTabChange}
                    sidebarOpen={sidebarOpen}
                    balance={sidebarBalance}
                    connected={connected}
                />

                {/* Main Content */}
                <main className="flex-1 p-4 md:p-6 min-h-[calc(100vh-57px)] overflow-y-auto">
                    {/* Real-time prices ticker */}
                    <div className="mb-6">
                        <RealTimePrices />
                    </div>

                    {/* Tab Content */}
                    {renderTabContent()}
                </main>
            </div>
        </div>
    );
}