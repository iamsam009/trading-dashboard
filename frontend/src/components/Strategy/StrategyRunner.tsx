"use client";

import React, { useState, useCallback } from "react";
import { toast } from "react-hot-toast";
import api from "@/lib/api";
import { useTradingStore, type Strategy } from "@/store/useTradingStore";

// ── Skeleton ─────────────────────────────────────────────────

export function StrategyRunnerSkeleton() {
    return (
        <div className="bg-slate-900 border border-slate-700 rounded-xl p-4 animate-pulse">
            <div className="h-4 w-24 bg-slate-700 rounded mb-3" />
            {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="h-12 bg-slate-800 rounded-lg mb-2" />
            ))}
        </div>
    );
}

// ── Empty State ──────────────────────────────────────────────

function EmptyState() {
    return (
        <div className="bg-slate-900 border border-slate-700 rounded-xl p-8 text-center">
            <div className="text-3xl mb-2">🤖</div>
            <p className="text-slate-400 text-sm">No strategies configured</p>
            <p className="text-slate-600 text-xs mt-1">
                Create strategies from the{" "}
                <a href="/strategies" className="text-cyan-400 hover:underline">
                    Strategies page
                </a>
            </p>
        </div>
    );
}

// ── Strategy Card ────────────────────────────────────────────

interface StrategyCardProps {
    strategy: Strategy;
    onToggle: (id: number) => Promise<void>;
    toggling: number | null;
}

function StrategyCard({ strategy, onToggle, toggling }: StrategyCardProps) {
    const isBusy = toggling === strategy.id;

    return (
        <div className="flex items-center justify-between bg-slate-800/50 border border-slate-700 rounded-lg px-4 py-3 hover:border-slate-500 transition">
            <div className="flex items-center gap-3 min-w-0">
                {/* Status indicator */}
                <div
                    className={`w-2 h-2 rounded-full flex-shrink-0 ${strategy.is_active ? "bg-emerald-400 animate-pulse" : "bg-slate-600"
                        }`}
                />
                <div className="min-w-0">
                    <div className="text-sm font-semibold text-white truncate">
                        {strategy.name}
                    </div>
                    {strategy.description && (
                        <div className="text-xs text-slate-500 truncate">
                            {strategy.description}
                        </div>
                    )}
                    <div className="flex items-center gap-1 mt-1 flex-wrap">
                        {strategy.symbols.map((s) => (
                            <span
                                key={s}
                                className="text-[10px] font-mono text-slate-400 bg-slate-700/50 px-1.5 py-0.5 rounded"
                            >
                                {s}
                            </span>
                        ))}
                    </div>
                </div>
            </div>

            <button
                onClick={() => onToggle(strategy.id)}
                disabled={isBusy}
                className={`flex-shrink-0 ml-3 px-4 py-1.5 rounded-lg text-xs font-semibold transition-all ${strategy.is_active
                        ? "bg-red-600/20 text-red-400 border border-red-600/30 hover:bg-red-600/30"
                        : "bg-emerald-600/20 text-emerald-400 border border-emerald-600/30 hover:bg-emerald-600/30"
                    } disabled:opacity-50 disabled:cursor-wait`}
            >
                {isBusy ? (
                    <span className="flex items-center gap-1">
                        <svg
                            className="animate-spin h-3 w-3"
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
                        ...
                    </span>
                ) : strategy.is_active ? (
                    "⏹ Stop"
                ) : (
                    "▶ Start"
                )}
            </button>
        </div>
    );
}

// ── Main Component ──────────────────────────────────────────

interface StrategyRunnerProps {
    strategies?: Strategy[];
    isLoading?: boolean;
}

export default function StrategyRunner({
    strategies: propStrategies,
    isLoading: propLoading,
}: StrategyRunnerProps) {
    const storeStrategies = useTradingStore((s) => s.strategies);
    const storeLoading = useTradingStore((s) => s.strategiesLoading);
    const toggleStrategyActive = useTradingStore((s) => s.toggleStrategyActive);

    const strategies = propStrategies ?? storeStrategies;
    const isLoading = propLoading ?? storeLoading;

    const [toggling, setToggling] = useState<number | null>(null);

    const handleToggle = useCallback(
        async (id: number) => {
            setToggling(id);
            try {
                const strategy = strategies.find((s) => s.id === id);
                const newActive = !strategy?.is_active;

                await api.put(`/strategies/${id}`, {
                    is_active: newActive,
                });

                toggleStrategyActive(id);
                toast.success(
                    newActive
                        ? `Strategy "${strategy?.name}" started`
                        : `Strategy "${strategy?.name}" stopped`,
                );
            } catch {
                // Interceptor handles toast
            } finally {
                setToggling(null);
            }
        },
        [strategies, toggleStrategyActive],
    );

    if (isLoading) {
        return <StrategyRunnerSkeleton />;
    }

    if (strategies.length === 0) {
        return <EmptyState />;
    }

    const activeCount = strategies.filter((s) => s.is_active).length;

    return (
        <div className="bg-slate-900 border border-slate-700 rounded-xl p-4">
            <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wider">
                    Strategy Runner
                </h3>
                <span className="text-xs text-slate-500">
                    {activeCount}/{strategies.length} active
                </span>
            </div>
            <div className="space-y-2">
                {strategies.map((s) => (
                    <StrategyCard
                        key={s.id}
                        strategy={s}
                        onToggle={handleToggle}
                        toggling={toggling}
                    />
                ))}
            </div>
        </div>
    );
}