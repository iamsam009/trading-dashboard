/**
 * Zustand store for real-time trading data.
 *
 * Manages position state, balance, trade history, and performance metrics
 * that are updated via WebSocket push events and REST API polling.
 */

import { create } from "zustand";

// ── Types ────────────────────────────────────────────────────

export interface Position {
    id: number;
    symbol: string;
    side: "LONG" | "SHORT";
    entry_price: number;
    mark_price: number | null;
    current_price: number | null;
    quantity: number;
    leverage: number;
    unrealized_pnl: number;
    unrealized_pnl_percent: number;
    realized_pnl: number;
    liquidation_price: number | null;
    margin_used: number;
    status: "OPEN" | "CLOSED" | "LIQUIDATED";
    updated_at: string | null;
}

export interface Balance {
    total_equity: number;
    total_used_margin: number;
    total_available: number;
    total_unrealized_pnl: number;
    balances: WalletBalance[];
}

export interface WalletBalance {
    asset: string;
    wallet_balance: number;
    available_balance: number;
    used_margin: number;
    unrealized_pnl: number;
}

export interface TradeRecord {
    id: number;
    symbol: string;
    side: "BUY" | "SELL";
    order_type: string;
    quantity: number;
    price: number | null;
    pnl: number | null;
    pnl_percent: number | null;
    fees: number | null;
    status: string;
    exchange_order_id: string | null;
    created_at: string | null;
    closed_at: string | null;
}

export interface PerformanceMetrics {
    total_pnl: number;
    total_pnl_percent: number;
    win_rate: number;
    profit_factor: number;
    sharpe_ratio: number;
    max_drawdown_percent: number;
    total_trades: number;
    winning_trades: number;
    losing_trades: number;
    equity_curve: EquityPoint[];
}

export interface EquityPoint {
    ts: string;
    equity: number;
}

export interface Strategy {
    id: number;
    name: string;
    description: string | null;
    is_active: boolean;
    symbols: string[];
    version: number;
}

export interface PnlUpdate {
    position_id: number;
    unrealized_pnl: number;
    unrealized_pnl_percent: number;
    current_price: number;
}

// ── Store State ──────────────────────────────────────────────

export interface TradingState {
    // Data
    positions: Position[];
    balance: Balance | null;
    trades: TradeRecord[];
    tradesTotal: number;
    tradesPage: number;
    metrics: PerformanceMetrics | null;
    strategies: Strategy[];
    dailyPnl: number;

    // Loading states
    positionsLoading: boolean;
    balanceLoading: boolean;
    tradesLoading: boolean;
    metricsLoading: boolean;
    strategiesLoading: boolean;

    // Actions
    setPositions: (positions: Position[]) => void;
    setPositionsLoading: (loading: boolean) => void;
    updatePositionPnl: (update: PnlUpdate) => void;

    setBalance: (balance: Balance) => void;
    setBalanceLoading: (loading: boolean) => void;

    setTrades: (trades: TradeRecord[], total: number, page: number) => void;
    appendTrades: (trades: TradeRecord[], total: number, page: number) => void;
    setTradesLoading: (loading: boolean) => void;

    setMetrics: (metrics: PerformanceMetrics) => void;
    setMetricsLoading: (loading: boolean) => void;

    setStrategies: (strategies: Strategy[]) => void;
    setStrategiesLoading: (loading: boolean) => void;
    toggleStrategyActive: (id: number) => void;

    setDailyPnl: (pnl: number) => void;

    reset: () => void;
}

// ── Initial State ────────────────────────────────────────────

const initialState = {
    positions: [],
    balance: null,
    trades: [],
    tradesTotal: 0,
    tradesPage: 1,
    metrics: null,
    strategies: [],
    dailyPnl: 0,
    positionsLoading: false,
    balanceLoading: false,
    tradesLoading: false,
    metricsLoading: false,
    strategiesLoading: false,
};

// ── Store ────────────────────────────────────────────────────

export const useTradingStore = create<TradingState>((set) => ({
    ...initialState,

    // Positions
    setPositions: (positions) => set({ positions, positionsLoading: false }),
    setPositionsLoading: (loading) => set({ positionsLoading: loading }),

    updatePositionPnl: (update) =>
        set((state) => ({
            positions: state.positions.map((p) =>
                p.id === update.position_id
                    ? {
                        ...p,
                        unrealized_pnl: update.unrealized_pnl,
                        unrealized_pnl_percent: update.unrealized_pnl_percent,
                        current_price: update.current_price,
                    }
                    : p,
            ),
        })),

    // Balance
    setBalance: (balance) => set({ balance, balanceLoading: false }),
    setBalanceLoading: (loading) => set({ balanceLoading: loading }),

    // Trades
    setTrades: (trades, total, page) =>
        set({ trades, tradesTotal: total, tradesPage: page, tradesLoading: false }),
    appendTrades: (trades, total, page) =>
        set((state) => ({
            trades: [...state.trades, ...trades],
            tradesTotal: total,
            tradesPage: page,
            tradesLoading: false,
        })),
    setTradesLoading: (loading) => set({ tradesLoading: loading }),

    // Metrics
    setMetrics: (metrics) => set({ metrics, metricsLoading: false }),
    setMetricsLoading: (loading) => set({ metricsLoading: loading }),

    // Strategies
    setStrategies: (strategies) => set({ strategies, strategiesLoading: false }),
    setStrategiesLoading: (loading) => set({ strategiesLoading: loading }),
    toggleStrategyActive: (id) =>
        set((state) => ({
            strategies: state.strategies.map((s) =>
                s.id === id ? { ...s, is_active: !s.is_active } : s,
            ),
        })),

    // Daily PnL
    setDailyPnl: (pnl) => set({ dailyPnl: pnl }),

    // Reset
    reset: () => set(initialState),
}));