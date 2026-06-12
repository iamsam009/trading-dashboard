/**
 * useWebSocket – React hook that connects to the backend WebSocket
 * and populates the Zustand dashboard store with real-time data.
 *
 * Features:
 * - Automatic reconnection with exponential backoff
 * - Ping/pong heartbeat handling
 * - Symbol subscribe/unsubscribe
 * - Parses all message types: initial_snapshot, market_price, trade_notification, pnl_update
 *
 * Usage:
 * ```tsx
 * function Dashboard() {
 *   const { connected, symbols } = useWebSocket(userId, token);
 *   if (!connected) return <Spinner />;
 *   return <RealTimePrices symbols={symbols} />;
 * }
 * ```
 */
"use client";

import { useEffect, useRef, useCallback } from "react";
import { useDashboardStore } from "@/store/dashboardStore";

// ── Constants ────────────────────────────────────────────────────────

const RECONNECT_BASE_DELAY = 1000; // 1 second
const RECONNECT_MAX_DELAY = 30000; // 30 seconds
const PING_INTERVAL = 25000; // 25 seconds – must match backend HEARTBEAT_INTERVAL

// ── Helpers ──────────────────────────────────────────────────────────

function getWsUrl(userId: number, token: string): string {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = process.env.NEXT_PUBLIC_API_HOST || window.location.host;
    return `${protocol}//${host}/api/v1/ws/${userId}?token=${encodeURIComponent(token)}`;
}

// ── Hook ─────────────────────────────────────────────────────────────

export function useWebSocket(userId: number | null, token: string | null) {
    const wsRef = useRef<WebSocket | null>(null);
    const reconnectAttempt = useRef(0);
    const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
    const pingTimer = useRef<ReturnType<typeof setInterval> | null>(null);

    const {
        setConnected,
        setUserId,
        setSubscribedSymbols,
        updateMarketPrice,
        setPositions,
        setBalance,
        addTradeNotification,
    } = useDashboardStore();

    // ── Message handler ──────────────────────────────────────────

    const handleMessage = useCallback(
        (event: MessageEvent) => {
            try {
                const msg = JSON.parse(event.data);

                switch (msg.type) {
                    case "connected":
                        setConnected(true);
                        setUserId(userId);
                        setSubscribedSymbols(msg.subscribed_symbols || []);
                        break;

                    case "initial_snapshot": {
                        const data = msg.data;
                        if (data.balance) {
                            setBalance({
                                total_balance: data.balance.total_balance ?? 0,
                                available_balance: data.balance.available_balance ?? 0,
                                unrealized_pnl: data.balance.unrealized_pnl ?? 0,
                                wallet_balance: data.balance.wallet_balance ?? 0,
                            });
                        }
                        if (data.positions) {
                            setPositions(data.positions);
                        }
                        break;
                    }

                    case "market_price":
                        updateMarketPrice(msg.data.symbol, msg.data);
                        break;

                    case "trade_notification":
                        addTradeNotification(msg.data);
                        break;

                    case "pnl_update":
                        // PNL updates come in with the same shape as balance
                        if (msg.data) {
                            setBalance({
                                total_balance: msg.data.total_balance ?? 0,
                                available_balance: msg.data.available_balance ?? 0,
                                unrealized_pnl: msg.data.unrealized_pnl ?? 0,
                                wallet_balance: msg.data.wallet_balance ?? 0,
                            });
                        }
                        break;

                    case "ping":
                        // Respond with pong
                        wsRef.current?.send(JSON.stringify({ type: "pong" }));
                        break;

                    case "subscribed":
                        setSubscribedSymbols(msg.symbols || []);
                        break;

                    default:
                        break;
                }
            } catch {
                // Ignore malformed messages
            }
        },
        [userId, setConnected, setUserId, setSubscribedSymbols, updateMarketPrice, setPositions, setBalance, addTradeNotification]
    );

    // ── Connect ──────────────────────────────────────────────────

    const connect = useCallback(() => {
        if (!userId || !token) return;

        // Clean up any existing connection
        if (wsRef.current) {
            wsRef.current.onclose = null; // prevent reconnect triggering on intentional close
            wsRef.current.close();
        }

        const url = getWsUrl(userId, token);
        const ws = new WebSocket(url);
        wsRef.current = ws;

        ws.onopen = () => {
            reconnectAttempt.current = 0;
            // Start pinging
            pingTimer.current = setInterval(() => {
                if (ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({ type: "ping" }));
                }
            }, PING_INTERVAL);
        };

        ws.onmessage = handleMessage;

        ws.onclose = (event) => {
            setConnected(false);
            if (pingTimer.current) {
                clearInterval(pingTimer.current);
                pingTimer.current = null;
            }

            // Don't reconnect on auth failures (4001, 4003)
            if (event.code === 4001 || event.code === 4003) {
                return;
            }

            // Exponential backoff reconnect
            const delay = Math.min(
                RECONNECT_BASE_DELAY * Math.pow(2, reconnectAttempt.current),
                RECONNECT_MAX_DELAY
            );
            reconnectAttempt.current += 1;

            reconnectTimer.current = setTimeout(() => {
                connect();
            }, delay);
        };

        ws.onerror = () => {
            // onclose will fire after this, triggering reconnect
        };
    }, [userId, token, handleMessage, setConnected]);

    // ── Subscribe / Unsubscribe helpers ─────────────────────────

    const subscribe = useCallback((symbols: string[]) => {
        if (wsRef.current?.readyState === WebSocket.OPEN) {
            wsRef.current.send(JSON.stringify({ type: "subscribe", symbols }));
        }
    }, []);

    const unsubscribe = useCallback((symbols: string[]) => {
        if (wsRef.current?.readyState === WebSocket.OPEN) {
            wsRef.current.send(JSON.stringify({ type: "unsubscribe", symbols }));
        }
    }, []);

    // ── Lifecycle ────────────────────────────────────────────────

    useEffect(() => {
        connect();

        return () => {
            if (reconnectTimer.current) {
                clearTimeout(reconnectTimer.current);
            }
            if (pingTimer.current) {
                clearInterval(pingTimer.current);
            }
            if (wsRef.current) {
                wsRef.current.onclose = null;
                wsRef.current.close();
            }
            setConnected(false);
        };
    }, [connect, setConnected]);

    return {
        subscribe,
        unsubscribe,
    };
}