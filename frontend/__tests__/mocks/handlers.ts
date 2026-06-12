/**
 * MSW (Mock Service Worker) HTTP request handlers.
 *
 * Each handler intercepts a specific API route and returns controlled
 * test data so components don't need a running backend.
 */

import { http, HttpResponse } from "msw";
import { makePosition, makePositions, makeBalance, makeTrade, makeTrades, makeMetrics, makeStrategy, makeStrategies, makeRiskStatus, makeRiskSettings } from "./data";

const BASE_URL = "http://localhost/api/v1";
const BASE_URL_8000 = "http://localhost:8000/api/v1";

export const handlers = [
    // ── Dashboard ─────────────────────────────────────────

    // GET /dashboard/overview
    http.get(`${BASE_URL}/dashboard/overview`, () => {
        return HttpResponse.json({
            metrics: makeMetrics(),
            daily_pnl: 250,
            balance: makeBalance(),
            equity_curve: [
                { ts: "2026-06-10T00:00:00Z", equity: 10000 },
                { ts: "2026-06-11T00:00:00Z", equity: 12500 },
                { ts: "2026-06-12T00:00:00Z", equity: 15000 },
            ],
        });
    }),

    // GET /dashboard/balance
    http.get(`${BASE_URL}/dashboard/balance`, () => {
        return HttpResponse.json(makeBalance());
    }),

    // GET /dashboard/positions
    http.get(`${BASE_URL}/dashboard/positions`, () => {
        return HttpResponse.json(makePositions(3));
    }),

    // GET /dashboard/strategies
    http.get(`${BASE_URL}/dashboard/strategies`, () => {
        return HttpResponse.json(makeStrategies(4));
    }),

    // ── Trading ───────────────────────────────────────────

    // GET /trading/balance
    http.get(`${BASE_URL}/trading/balance`, () => {
        return HttpResponse.json(makeBalance());
    }),

    // GET /trading/positions
    http.get(`${BASE_URL}/trading/positions`, () => {
        return HttpResponse.json(makePositions(3));
    }),

    // GET /trading/orders
    http.get(`${BASE_URL}/trading/orders`, ({ request }) => {
        const url = new URL(request.url);
        const page = parseInt(url.searchParams.get("page") ?? "1", 10);
        const size = parseInt(url.searchParams.get("size") ?? "20", 10);
        const allTrades = makeTrades(25);
        const start = (page - 1) * size;
        const pageTrades = allTrades.slice(start, start + size);
        return HttpResponse.json({
            orders: pageTrades,
            total: allTrades.length,
            page,
            size,
        });
    }),

    // ── Strategies ────────────────────────────────────────

    // GET /strategies
    http.get(`${BASE_URL}/strategies`, () => {
        return HttpResponse.json(makeStrategies(4));
    }),

    // POST /strategies/:id/validate
    http.post(`${BASE_URL}/strategies/:id/validate`, async ({ request }) => {
        const body = await request.json() as Record<string, unknown>;
        const def = (body.json_definition as Record<string, unknown>) || {};
        // If the definition has no conditions, treat as invalid
        if (!def.conditions || (def.conditions as unknown[]).length === 0) {
            return HttpResponse.json({
                valid: false,
                errors: ["At least one condition is required"],
                strategy_name: (def.name as string) || "",
                indicators_used: [],
                symbols: [],
            });
        }
        return HttpResponse.json({
            valid: true,
            errors: [],
            strategy_name: (def.name as string) || "Unnamed",
            indicators_used: ["SMA", "RSI"],
            symbols: (def.symbols as string[]) || ["BTCUSDT"],
        });
    }),

    // PUT /strategies/:id
    http.put(`${BASE_URL}/strategies/:id`, async ({ params, request }) => {
        const body = await request.json() as Record<string, unknown>;
        const id = Number(params.id);
        const strategy = makeStrategy({ id, is_active: body.is_active as boolean });
        return HttpResponse.json(strategy);
    }),

    // DELETE /strategies/:id
    http.delete(`${BASE_URL}/strategies/:id`, () => {
        return HttpResponse.json({ detail: "Strategy deleted" });
    }),

    // ── Risk (via API proxy) ──────────────────────────────

    // GET /risk/status
    http.get(`${BASE_URL}/risk/status`, () => {
        return HttpResponse.json(makeRiskStatus());
    }),

    // GET /risk/settings
    http.get(`${BASE_URL}/risk/settings`, () => {
        return HttpResponse.json(makeRiskSettings());
    }),

    // PUT /risk/settings
    http.put(`${BASE_URL}/risk/settings`, async ({ request }) => {
        const body = await request.json() as Record<string, unknown>;
        return HttpResponse.json(makeRiskSettings(body));
    }),

    // POST /risk/kill-switch
    http.post(`${BASE_URL}/risk/kill-switch`, async ({ request }) => {
        const body = await request.json() as Record<string, unknown>;
        return HttpResponse.json({
            kill_switch_enabled: body.enabled ?? true,
            message: body.enabled === false ? "Kill-switch disengaged" : "Kill-switch engaged",
        });
    }),

    // ── Risk (via localhost:8000) – RiskPanel component uses axios with baseURL http://localhost:8000 ──

    // GET /risk/status
    http.get(`${BASE_URL_8000}/risk/status`, () => {
        return HttpResponse.json(makeRiskStatus());
    }),

    // GET /risk/settings
    http.get(`${BASE_URL_8000}/risk/settings`, () => {
        return HttpResponse.json(makeRiskSettings());
    }),

    // PUT /risk/settings
    http.put(`${BASE_URL_8000}/risk/settings`, async ({ request }) => {
        const body = await request.json() as Record<string, unknown>;
        return HttpResponse.json(makeRiskSettings(body));
    }),

    // POST /risk/kill-switch
    http.post(`${BASE_URL_8000}/risk/kill-switch`, async ({ request }) => {
        const body = await request.json() as Record<string, unknown>;
        return HttpResponse.json({
            kill_switch_enabled: body.enabled ?? true,
            message: body.enabled === false ? "Kill-switch disengaged" : "Kill-switch engaged",
        });
    }),
];