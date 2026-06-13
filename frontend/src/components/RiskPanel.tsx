"use client";

/**
 * RiskPanel – Dashboard panel for risk management.
 *
 * Shows today's PnL vs daily loss limit, drawdown gauge, kill-switch button,
 * editable risk parameters, and trailing-stop statuses.
 */

import React, { useEffect, useState, useCallback } from "react";
import api from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TrailingStopStatus {
    position_id: number;
    symbol: string;
    side: string;
    entry_price: number;
    current_price: number;
    peak_price: number;
    drawdown_from_peak_percent: number;
    trailing_stop_distance_percent: number;
    trailing_stop_triggered: boolean;
}

interface RiskStatus {
    daily_pnl: number;
    daily_loss_limit: number;
    daily_loss_used_percent: number;
    unrealized_pnl: number;
    max_drawdown_percent: number;
    current_drawdown_percent: number;
    open_positions: number;
    max_open_trades: number;
    kill_switch_enabled: boolean;
    trading_enabled: boolean;
    trailing_stops: TrailingStopStatus[];
    timestamp: string;
}

interface RiskSettings {
    daily_loss_limit: number;
    weekly_loss_limit: number;
    max_drawdown_percent: number;
    max_open_trades: number;
    position_size_percent: number;
    max_leverage: number;
    stop_loss_percent: number;
    take_profit_percent: number;
    trailing_stop_enabled: boolean;
    trailing_stop_distance_percent: number;
    risk_per_trade_percent: number;
    kill_switch_enabled: boolean;
    kill_switch_reason: string | null;
    trading_enabled: boolean;
}

// ---------------------------------------------------------------------------
// Helper – colour helpers
// ---------------------------------------------------------------------------

function gaugeColor(percent: number, danger: number, warn: number): string {
    if (percent >= danger) return "#ef4444"; // red
    if (percent >= warn) return "#f59e0b"; // amber
    return "#22c55e"; // green
}

function pnlColor(val: number): string {
    return val >= 0 ? "#22c55e" : "#ef4444";
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function GaugeBar({
    label,
    value,
    max,
    dangerPct = 80,
    warnPct = 50,
}: {
    label: string;
    value: number;
    max: number;
    dangerPct?: number;
    warnPct?: number;
}) {
    const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0;
    return (
        <div className="mb-3">
            <div className="flex justify-between text-xs text-slate-400 mb-1">
                <span>{label}</span>
                <span>
                    {value.toFixed(2)} / {max.toFixed(2)}
                </span>
            </div>
            <div className="h-3 rounded-full bg-slate-700 overflow-hidden">
                <div
                    className="h-full rounded-full transition-all duration-500"
                    style={{
                        width: `${pct}%`,
                        backgroundColor: gaugeColor(pct, dangerPct, warnPct),
                    }}
                />
            </div>
        </div>
    );
}

function DrawdownGauge({ current, max }: { current: number; max: number }) {
    const pct = max > 0 ? Math.min(current, max) : 0;
    return (
        <div className="mb-4">
            <div className="flex justify-between text-xs text-slate-400 mb-1">
                <span>Drawdown</span>
                <span className={current >= max ? "text-red-400 font-bold" : ""}>
                    {current.toFixed(2)}% / {max.toFixed(2)}%
                </span>
            </div>
            <div className="h-4 rounded-full bg-slate-700 overflow-hidden">
                <div
                    className="h-full rounded-full transition-all duration-500"
                    style={{
                        width: `${Math.min((current / max) * 100, 100)}%`,
                        backgroundColor: gaugeColor(current, max, max * 0.5),
                    }}
                />
            </div>
        </div>
    );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function RiskPanel() {
    const [status, setStatus] = useState<RiskStatus | null>(null);
    const [settings, setSettings] = useState<RiskSettings | null>(null);
    const [editMode, setEditMode] = useState(false);
    const [form, setForm] = useState<Partial<RiskSettings>>({});
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [killSwitchLoading, setKillSwitchLoading] = useState(false);

    // --- Fetch helpers ---

    const fetchStatus = useCallback(async () => {
        try {
            const { data } = await api.get<RiskStatus>("/api/v1/risk/status");
            setStatus(data);
            setError(null);
        } catch (err: any) {
            setError(err?.response?.data?.detail || "Failed to fetch risk status");
        }
    }, []);

    const fetchSettings = useCallback(async () => {
        try {
            const { data } = await api.get<RiskSettings>("/api/v1/risk/settings");
            setSettings(data);
            setForm(data);
            setError(null);
        } catch (err: any) {
            setError(err?.response?.data?.detail || "Failed to fetch risk settings");
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchSettings();
        fetchStatus();
        const interval = setInterval(fetchStatus, 5000); // poll every 5s
        return () => clearInterval(interval);
    }, [fetchSettings, fetchStatus]);

    // --- Kill switch ---

    const handleKillSwitch = async () => {
        setKillSwitchLoading(true);
        try {
            await api.post("/api/v1/risk/kill-switch", {
                enabled: !settings?.kill_switch_enabled,
                reason: settings?.kill_switch_enabled
                    ? "Manual disengage"
                    : "Manual kill-switch activation",
            });
            await fetchSettings();
            await fetchStatus();
        } catch (err: any) {
            setError(err?.response?.data?.detail || "Kill-switch toggle failed");
        } finally {
            setKillSwitchLoading(false);
        }
    };

    // --- Save settings ---

    const handleSaveSettings = async () => {
        try {
            const { data } = await api.put<RiskSettings>("/api/v1/risk/settings", form);
            setSettings(data);
            setEditMode(false);
            setError(null);
        } catch (err: any) {
            setError(err?.response?.data?.detail || "Failed to update settings");
        }
    };

    // --- Render ---

    if (loading) {
        return (
            <div className="bg-slate-900 border border-slate-700 rounded-xl p-5 text-slate-400">
                Loading risk data...
            </div>
        );
    }

    if (!settings) {
        return (
            <div className="bg-slate-900 border border-slate-700 rounded-xl p-5 text-slate-400">
                No risk settings configured.
            </div>
        );
    }

    return (
        <div className="bg-slate-900 border border-slate-700 rounded-xl p-5 space-y-5">
            {/* Header */}
            <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold text-white">Risk Management</h2>
                <div className="flex items-center gap-2">
                    {settings.kill_switch_enabled && (
                        <span className="px-2 py-0.5 text-xs font-bold bg-red-600 text-white rounded animate-pulse">
                            KILL SWITCH ACTIVE
                        </span>
                    )}
                    <button
                        onClick={handleKillSwitch}
                        disabled={killSwitchLoading}
                        className={`px-3 py-1.5 text-sm font-semibold rounded-lg transition ${settings.kill_switch_enabled
                            ? "bg-green-600 hover:bg-green-500 text-white"
                            : "bg-red-600 hover:bg-red-500 text-white animate-pulse"
                            } disabled:opacity-50`}
                    >
                        {killSwitchLoading
                            ? "..."
                            : settings.kill_switch_enabled
                                ? "🔓 Disengage"
                                : "🛑 Kill Switch"}
                    </button>
                </div>
            </div>

            {error && (
                <div className="bg-red-900/30 border border-red-700 rounded-lg px-3 py-2 text-sm text-red-300">
                    {error}
                </div>
            )}

            {/* Daily PnL */}
            {status && (
                <div className="space-y-3">
                    <div className="flex items-center justify-between">
                        <span className="text-sm text-slate-400">Today's PnL</span>
                        <span
                            className="text-lg font-bold"
                            style={{ color: pnlColor(status.daily_pnl) }}
                        >
                            ₹{status.daily_pnl.toFixed(2)}
                        </span>
                    </div>
                    <GaugeBar
                        label="Daily Loss"
                        value={status.daily_loss_used_percent}
                        max={100}
                        dangerPct={90}
                        warnPct={70}
                    />
                    <GaugeBar
                        label="Open Positions"
                        value={status.open_positions}
                        max={status.max_open_trades}
                        dangerPct={100}
                        warnPct={80}
                    />
                    <DrawdownGauge
                        current={status.current_drawdown_percent}
                        max={status.max_drawdown_percent}
                    />

                    {/* Unrealized PnL */}
                    <div className="flex justify-between text-sm">
                        <span className="text-slate-400">Unrealized PnL</span>
                        <span style={{ color: pnlColor(status.unrealized_pnl) }}>
                            ₹{status.unrealized_pnl.toFixed(2)}
                        </span>
                    </div>

                    {/* Trailing stops */}
                    {status.trailing_stops.length > 0 && (
                        <div className="mt-3">
                            <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">
                                Trailing Stops
                            </h3>
                            <div className="space-y-2">
                                {status.trailing_stops.map((ts) => (
                                    <div
                                        key={ts.position_id}
                                        className={`text-xs p-2 rounded border ${ts.trailing_stop_triggered
                                            ? "border-red-600 bg-red-900/20"
                                            : "border-slate-700 bg-slate-800"
                                            }`}
                                    >
                                        <div className="flex justify-between">
                                            <span className="font-semibold text-white">
                                                {ts.symbol} {ts.side}
                                            </span>
                                            <span className={ts.trailing_stop_triggered ? "text-red-400" : "text-slate-400"}>
                                                {ts.drawdown_from_peak_percent.toFixed(2)}%
                                            </span>
                                        </div>
                                        <div className="text-slate-500 mt-0.5">
                                            Entry: {ts.entry_price} | Peak: {ts.peak_price} | Now:{" "}
                                            {ts.current_price}
                                        </div>
                                        {ts.trailing_stop_triggered && (
                                            <div className="text-red-400 mt-1 font-bold">TRIGGERED</div>
                                        )}
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                </div>
            )}

            {/* Editable Settings */}
            <div className="border-t border-slate-700 pt-4">
                <div className="flex items-center justify-between mb-3">
                    <h3 className="text-sm font-semibold text-slate-300">Risk Parameters</h3>
                    <button
                        onClick={() => setEditMode(!editMode)}
                        className="text-xs text-blue-400 hover:text-blue-300"
                    >
                        {editMode ? "Cancel" : "Edit"}
                    </button>
                </div>

                {editMode ? (
                    <div className="space-y-3">
                        {[
                            { key: "daily_loss_limit", label: "Daily Loss Limit (₹)", type: "number" },
                            { key: "weekly_loss_limit", label: "Weekly Loss Limit (₹)", type: "number" },
                            { key: "max_drawdown_percent", label: "Max Drawdown %", type: "number" },
                            { key: "max_open_trades", label: "Max Open Trades", type: "number" },
                            { key: "position_size_percent", label: "Position Size %", type: "number" },
                            { key: "max_leverage", label: "Max Leverage", type: "number" },
                            { key: "stop_loss_percent", label: "Stop Loss %", type: "number" },
                            { key: "take_profit_percent", label: "Take Profit %", type: "number" },
                            { key: "risk_per_trade_percent", label: "Risk Per Trade %", type: "number" },
                            { key: "trailing_stop_distance_percent", label: "Trailing Stop Distance %", type: "number" },
                        ].map(({ key, label, type }) => (
                            <div key={key} className="flex items-center gap-2">
                                <label className="text-xs text-slate-400 w-44 shrink-0">{label}</label>
                                <input
                                    type={type}
                                    value={(form as any)[key] ?? ""}
                                    onChange={(e) =>
                                        setForm((prev) => ({
                                            ...prev,
                                            [key]: parseFloat(e.target.value) || 0,
                                        }))
                                    }
                                    className="flex-1 px-2 py-1 text-xs bg-slate-800 border border-slate-600 rounded text-white focus:outline-none focus:border-blue-500"
                                />
                            </div>
                        ))}

                        {/* Toggles */}
                        <div className="flex items-center gap-2">
                            <label className="text-xs text-slate-400 w-44 shrink-0">
                                Trailing Stop Enabled
                            </label>
                            <input
                                type="checkbox"
                                checked={form.trailing_stop_enabled ?? false}
                                onChange={(e) =>
                                    setForm((prev) => ({
                                        ...prev,
                                        trailing_stop_enabled: e.target.checked,
                                    }))
                                }
                                className="accent-blue-500"
                            />
                        </div>
                        <div className="flex items-center gap-2">
                            <label className="text-xs text-slate-400 w-44 shrink-0">
                                Trading Enabled
                            </label>
                            <input
                                type="checkbox"
                                checked={form.trading_enabled ?? false}
                                onChange={(e) =>
                                    setForm((prev) => ({
                                        ...prev,
                                        trading_enabled: e.target.checked,
                                    }))
                                }
                                className="accent-blue-500"
                            />
                        </div>

                        <button
                            onClick={handleSaveSettings}
                            className="w-full py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm font-semibold rounded-lg transition"
                        >
                            Save Settings
                        </button>
                    </div>
                ) : (
                    <div className="grid grid-cols-2 gap-2 text-xs">
                        <div className="text-slate-400">Daily Loss Limit:</div>
                        <div className="text-white">₹{settings.daily_loss_limit.toFixed(2)}</div>
                        <div className="text-slate-400">Max Drawdown:</div>
                        <div className="text-white">{settings.max_drawdown_percent}%</div>
                        <div className="text-slate-400">Max Open Trades:</div>
                        <div className="text-white">{settings.max_open_trades}</div>
                        <div className="text-slate-400">Position Size:</div>
                        <div className="text-white">{settings.position_size_percent}%</div>
                        <div className="text-slate-400">Max Leverage:</div>
                        <div className="text-white">{settings.max_leverage}x</div>
                        <div className="text-slate-400">Stop Loss:</div>
                        <div className="text-white">{settings.stop_loss_percent}%</div>
                        <div className="text-slate-400">Take Profit:</div>
                        <div className="text-white">{settings.take_profit_percent}%</div>
                        <div className="text-slate-400">Risk Per Trade:</div>
                        <div className="text-white">{settings.risk_per_trade_percent}%</div>
                        <div className="text-slate-400">Trailing Stop:</div>
                        <div className="text-white">
                            {settings.trailing_stop_enabled
                                ? `${settings.trailing_stop_distance_percent}%`
                                : "Disabled"}
                        </div>
                        <div className="text-slate-400">Trading:</div>
                        <div className={settings.trading_enabled ? "text-green-400" : "text-red-400"}>
                            {settings.trading_enabled ? "Enabled" : "Disabled"}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}