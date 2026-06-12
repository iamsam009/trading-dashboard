"use client";

import React, { useEffect, useRef } from "react";
import type { EquityPoint } from "@/store/useTradingStore";

// ── Skeleton ─────────────────────────────────────────────────

export function EquityChartSkeleton() {
    return (
        <div className="w-full h-[400px] bg-slate-900 border border-slate-700 rounded-xl animate-pulse flex items-center justify-center">
            <div className="text-slate-500 text-sm">Loading equity curve...</div>
        </div>
    );
}

// ── Empty State ──────────────────────────────────────────────

function EmptyState() {
    return (
        <div className="w-full h-[400px] bg-slate-900 border border-slate-700 rounded-xl flex items-center justify-center">
            <div className="text-center text-slate-500">
                <div className="text-3xl mb-2">📈</div>
                <p className="text-sm">No equity data available yet</p>
                <p className="text-xs mt-1 text-slate-600">
                    Start trading to see your equity curve
                </p>
            </div>
        </div>
    );
}

// ── Main Component ──────────────────────────────────────────

interface EquityChartProps {
    data: EquityPoint[];
    isLoading?: boolean;
}

export default function EquityChart({ data, isLoading = false }: EquityChartProps) {
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
                    secondsVisible: false,
                },
                rightPriceScale: {
                    borderColor: "#334155",
                },
                watermark: {
                    visible: true,
                    text: "Equity Curve",
                    fontSize: 24,
                    color: "rgba(148, 163, 184, 0.05)",
                    horzAlign: "center",
                    vertAlign: "center",
                },
            });

            // Area series for equity line
            const areaSeries = chart.addAreaSeries({
                lineColor: "#22d3ee",
                topColor: "rgba(34, 211, 238, 0.3)",
                bottomColor: "rgba(34, 211, 238, 0.02)",
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

            areaSeries.setData(chartData);
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

    if (isLoading) {
        return <EquityChartSkeleton />;
    }

    if (data.length === 0) {
        return <EmptyState />;
    }

    return (
        <div
            ref={containerRef}
            className="w-full rounded-xl overflow-hidden border border-slate-700"
        />
    );
}