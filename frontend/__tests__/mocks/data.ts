/**
 * Test fixture data factories for all dashboard domain types.
 *
 * Each factory returns sensible defaults with optional overrides so
 * individual tests can customize only the fields they care about.
 */

import type { Position, Balance, TradeRecord, PerformanceMetrics, Strategy, EquityPoint, WalletBalance } from "@/store/useTradingStore";

// ── Positions ────────────────────────────────────────────────

export function makePosition(overrides: Partial<Position> = {}): Position {
    return {
        id: 1,
        symbol: "BTCUSDT",
        side: "LONG",
        quantity: 0.5,
        entry_price: 62000,
        mark_price: 62500,
        current_price: 62500,
        leverage: 5,
        unrealized_pnl: 250,
        unrealized_pnl_percent: 0.81,
        realized_pnl: 0,
        liquidation_price: 55800,
        margin_used: 6200,
        status: "OPEN",
        updated_at: "2026-06-12T08:00:00Z",
        ...overrides,
    };
}

export function makePositions(count: number): Position[] {
    const symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "ADAUSDT"];
    return Array.from({ length: count }, (_, i) =>
        makePosition({
            id: i + 1,
            symbol: symbols[i % symbols.length],
            side: i % 2 === 0 ? "LONG" : "SHORT",
            entry_price: 100 + i * 10,
            current_price: 105 + i * 10,
            unrealized_pnl: (i % 2 === 0 ? 1 : -1) * (50 + i * 25),
            unrealized_pnl_percent: (i % 2 === 0 ? 1 : -1) * (0.5 + i * 0.25),
        }),
    );
}

// ── Balance ──────────────────────────────────────────────────

export function makeWalletBalance(overrides: Partial<WalletBalance> = {}): WalletBalance {
    return {
        asset: "USDT",
        wallet_balance: 15000,
        available_balance: 12000,
        used_margin: 3000,
        unrealized_pnl: 500,
        ...overrides,
    };
}

export function makeBalance(overrides: Partial<Balance> = {}): Balance {
    return {
        total_equity: 15000,
        total_used_margin: 3000,
        total_available: 12000,
        total_unrealized_pnl: 500,
        balances: [makeWalletBalance()],
        ...overrides,
    };
}

// ── Trades ───────────────────────────────────────────────────

export function makeTrade(overrides: Partial<TradeRecord> = {}): TradeRecord {
    return {
        id: 1,
        symbol: "BTCUSDT",
        side: "BUY",
        order_type: "LIMIT",
        quantity: 0.1,
        price: 62000,
        pnl: 150,
        pnl_percent: 0.24,
        fees: 2.5,
        status: "FILLED",
        exchange_order_id: null,
        created_at: "2026-06-12T07:30:00Z",
        closed_at: null,
        ...overrides,
    };
}

export function makeTrades(count: number): TradeRecord[] {
    return Array.from({ length: count }, (_, i) =>
        makeTrade({
            id: i + 1,
            symbol: i % 2 === 0 ? "BTCUSDT" : "ETHUSDT",
            side: i % 3 === 0 ? "SELL" : "BUY",
            pnl: (i % 2 === 0 ? 1 : -1) * (10 + i * 25),
            pnl_percent: (i % 2 === 0 ? 1 : -1) * (0.1 + i * 0.15),
            // Keep hours in valid 0-23 range; offset from 7 and wrap
            created_at: `2026-06-12T${String((7 + i) % 24).padStart(2, "0")}:00:00Z`,
        }),
    );
}

// ── Performance Metrics ──────────────────────────────────────

export function makeMetrics(overrides: Partial<PerformanceMetrics> = {}): PerformanceMetrics {
    return {
        total_pnl: 3200,
        total_pnl_percent: 21.33,
        total_trades: 156,
        winning_trades: 98,
        losing_trades: 58,
        win_rate: 62.82,
        profit_factor: 1.85,
        sharpe_ratio: 1.42,
        max_drawdown_percent: -12.5,
        equity_curve: [],
        ...overrides,
    };
}

// ── Strategies ───────────────────────────────────────────────

export function makeStrategy(overrides: Record<string, any> = {}): Record<string, any> {
    return {
        id: 1,
        user_id: 1,
        name: "BTC Momentum",
        description: "BTC momentum strategy with RSI crossover",
        json_definition: {
            name: "BTC Momentum",
            description: "BTC momentum strategy with RSI crossover",
            conditions: [
                {
                    indicator: "RSI",
                    params: [14],
                    crossover: "SMA",
                    compare_params: [21],
                },
            ],
            action: "BUY",
            quantity_percent: 10,
            symbols: ["BTCUSDT"],
            timeframe: "1h",
        },
        is_active: false,
        symbols: ["BTCUSDT"],
        version: 1,
        tags: null,
        created_at: "2026-06-01T00:00:00Z",
        updated_at: "2026-06-10T00:00:00Z",
        ...overrides,
    };
}

export function makeStrategies(count: number): Record<string, any>[] {
    const names = ["BTC Momentum", "ETH Mean Reversion", "SOL Breakout", "ADA Scalper"];
    return Array.from({ length: count }, (_, i) =>
        makeStrategy({
            id: i + 1,
            name: names[i] ?? `Strategy ${i + 1}`,
            is_active: i === 0,
            symbols: [["BTCUSDT"], ["ETHUSDT"], ["SOLUSDT"], ["ADAUSDT"]][i] ?? ["BTCUSDT"],
        }),
    );
}

// ── Equity Curve ─────────────────────────────────────────────

export function makeEquityPoint(overrides: Partial<EquityPoint> = {}): EquityPoint {
    return {
        ts: "2026-06-12T08:00:00Z",
        equity: 15000,
        ...overrides,
    };
}

export function makeEquityCurve(days: number): EquityPoint[] {
    const points: EquityPoint[] = [];
    let equity = 10000;
    for (let i = 0; i < days; i++) {
        equity += (Math.random() - 0.45) * 200;
        points.push({
            ts: new Date(2026, 5, 1 + i).toISOString(),
            equity: Math.round(equity * 100) / 100,
        });
    }
    return points;
}

// ── Risk Status ──────────────────────────────────────────────

export function makeRiskStatus(overrides: Record<string, any> = {}): Record<string, any> {
    return {
        daily_pnl: 250,
        daily_loss_limit: 1000,
        daily_loss_used_percent: 25,
        unrealized_pnl: 500,
        max_drawdown_percent: 25,
        current_drawdown_percent: 5.2,
        open_positions: 3,
        max_open_trades: 10,
        kill_switch_enabled: false,
        trading_enabled: true,
        trailing_stops: [
            {
                position_id: 1,
                symbol: "BTCUSDT",
                side: "LONG",
                entry_price: 62000,
                current_price: 62500,
                peak_price: 63000,
                drawdown_from_peak_percent: 0.79,
                trailing_stop_distance_percent: 5,
                trailing_stop_triggered: false,
            },
            {
                position_id: 2,
                symbol: "ETHUSDT",
                side: "SHORT",
                entry_price: 3400,
                current_price: 3450,
                peak_price: 3500,
                drawdown_from_peak_percent: 1.43,
                trailing_stop_distance_percent: 5,
                trailing_stop_triggered: false,
            },
        ],
        timestamp: "2026-06-12T08:00:00Z",
        ...overrides,
    };
}

export function makeRiskSettings(overrides: Record<string, any> = {}): Record<string, any> {
    return {
        daily_loss_limit: 1000,
        weekly_loss_limit: 5000,
        max_drawdown_percent: 25,
        max_open_trades: 10,
        position_size_percent: 5,
        max_leverage: 10,
        stop_loss_percent: 2,
        take_profit_percent: 5,
        trailing_stop_enabled: true,
        trailing_stop_distance_percent: 5,
        risk_per_trade_percent: 2,
        kill_switch_enabled: false,
        kill_switch_reason: null,
        trading_enabled: true,
        ...overrides,
    };
}