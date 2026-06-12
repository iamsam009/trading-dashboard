/**
 * Zustand store for real-time market data, positions, and trade notifications.
 *
 * Populated by the useWebSocket hook – components subscribe to slices
 * they care about (e.g. marketData, positions, trades).
 */
import { create } from "zustand";

// ── Types ────────────────────────────────────────────────────────────

export interface MarketPrice {
    symbol: string;
    price: number;
    high_24h: number;
    low_24h: number;
    volume_24h: number;
    change_percent: number;
    timestamp: string;
}

export interface Position {
    symbol: string;
    side: string;
    quantity: number;
    entry_price: number;
    mark_price: number;
    unrealized_pnl: number;
    leverage: number;
    status: string;
}

export interface TradeNotification {
    symbol: string;
    action: string;
    quantity: number;
    price: number;
    status: string;
    timestamp: string;
}

export interface Balance {
    total_balance: number;
    available_balance: number;
    unrealized_pnl: number;
    wallet_balance: number;
}

export interface DashboardState {
    // Connection
    connected: boolean;
    userId: number | null;
    subscribedSymbols: string[];

    // Market data: symbol → MarketPrice
    marketData: Record<string, MarketPrice>;

    // Positions
    positions: Position[];

    // Account
    balance: Balance | null;

    // Recent trade notifications
    tradeNotifications: TradeNotification[];

    // Actions
    setConnected: (connected: boolean) => void;
    setUserId: (userId: number | null) => void;
    setSubscribedSymbols: (symbols: string[]) => void;
    updateMarketPrice: (symbol: string, price: MarketPrice) => void;
    setPositions: (positions: Position[]) => void;
    setBalance: (balance: Balance | null) => void;
    addTradeNotification: (trade: TradeNotification) => void;
    reset: () => void;
}

const initialState = {
    connected: false,
    userId: null as number | null,
    subscribedSymbols: [] as string[],
    marketData: {} as Record<string, MarketPrice>,
    positions: [] as Position[],
    balance: null as Balance | null,
    tradeNotifications: [] as TradeNotification[],
};

export const useDashboardStore = create<DashboardState>((set) => ({
    ...initialState,

    setConnected: (connected: boolean) => set({ connected }),

    setUserId: (userId: number | null) => set({ userId }),

    setSubscribedSymbols: (symbols: string[]) =>
        set({ subscribedSymbols: symbols }),

    updateMarketPrice: (symbol: string, price: MarketPrice) =>
        set((state) => ({
            marketData: { ...state.marketData, [symbol]: price },
        })),

    setPositions: (positions: Position[]) => set({ positions }),

    setBalance: (balance: Balance | null) => set({ balance }),

    addTradeNotification: (trade: TradeNotification) =>
        set((state) => ({
            tradeNotifications: [trade, ...state.tradeNotifications].slice(0, 50),
        })),

    reset: () => set(initialState),
}));