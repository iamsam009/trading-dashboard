"use client";

import React, { useMemo } from "react";
import { useTradingStore, type PerformanceMetrics } from "@/store/useTradingStore";

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

function fmtNumber(v: number, decimals = 2): string {
    return v.toFixed(decimals);
}

// ── Skeleton ─────────────────────────────────────────────────

function CardSkeleton() {
    return (
        <div className="bg-slate-900 border border-slate-700 rounded-xl p-4 animate-pulse">
            <div className="h-3 w-20 bg-slate-700 rounded mb-3" />
            <div className="h-6 w-28 bg-slate-700 rounded mb-2" />
            <div className="h-3 w-16 bg-slate-700 rounded" />
        </div>
    );
}

export function MetricsCardsSkeleton() {
    return (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
            {Array.from({ length: 6 }).map((_, i) => (
                <CardSkeleton key={i} />
            ))}
        </div>
    );
}

// ── Metric Card ──────────────────────────────────────────────

interface MetricCardProps {
    label: string;
    value: string;
    sub?: string;
    colorClass?: string;
    icon?: string;
}

function MetricCard({ label, value, sub, colorClass = "text-white", icon }: MetricCardProps) {
    return (
        <div className="bg-slate-900 border border-slate-700 rounded-xl p-4 hover:border-slate-500 transition-colors">
            <div className="flex items-center gap-2 mb-1">
                {icon && <span className="text-sm">{icon}</span>}
                <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                    {label}
                </span>
            </div>
            <div className={`text-xl font-bold font-mono ${colorClass}`}>{value}</div>
            {sub !== undefined && (
                <div className="text-xs text-slate-500 mt-1">{sub}</div>
            )}
        </div>
    );
}

// ─── Main Component ──────────────────────────────────────────

interface MetricsCardsProps {
    metrics?: PerformanceMetrics | null;
    dailyPnl?: number;
    isLoading?: boolean;
}

export default function MetricsCards({
    metrics,
    dailyPnl = 0,
    isLoading = false,
}: MetricsCardsProps) {
    const storeMetrics = useTradingStore((s) => s.metrics);
    const storeDailyPnl = useTradingStore((s) => s.dailyPnl);

    const effectiveMetrics = metrics ?? storeMetrics;
    const effectiveDailyPnl = metrics ? dailyPnl : storeDailyPnl;

    if (isLoading || !effectiveMetrics) {
        return <MetricsCardsSkeleton />;
    }

    const m = effectiveMetrics;

    return (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
            <MetricCard
                label="Daily P&L"
                value={fmtCurrency(effectiveDailyPnl)}
                colorClass={effectiveDailyPnl >= 0 ? "text-emerald-400" : "text-red-400"}
                icon="💰"
            />
            <MetricCard
                label="Total P&L"
                value={fmtCurrency(m.total_pnl)}
                sub={fmtPct(m.total_pnl_percent)}
                colorClass={m.total_pnl >= 0 ? "text-emerald-400" : "text-red-400"}
            />
            <MetricCard
                label="Win Rate"
                value={fmtPct(m.win_rate)}
                sub={`${m.winning_trades}W / ${m.losing_trades}L`}
                colorClass="text-cyan-400"
            />
            <MetricCard
                label="Sharpe Ratio"
                value={fmtNumber(m.sharpe_ratio)}
                colorClass="text-yellow-400"
                icon="📊"
            />
            <MetricCard
                label="Max Drawdown"
                value={fmtPct(m.max_drawdown_percent)}
                colorClass="text-red-400"
                icon="📉"
            />
            <MetricCard
                label="Profit Factor"
                value={fmtNumber(m.profit_factor)}
                sub={`${m.total_trades} trades`}
                colorClass={m.profit_factor >= 1 ? "text-emerald-400" : "text-red-400"}
            />
        </div>
    );
}