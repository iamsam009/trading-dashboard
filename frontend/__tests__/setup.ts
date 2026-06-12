/**
 * Jest global setup (setupFiles) – runs BEFORE the test framework.
 *
 * NOTE: The custom test environment (jsdom-extended-env.ts) injects
 * Request/Response/Headers/fetch into the jsdom global so MSW v2 works.
 *
 * Responsibilities:
 *  1. Mock browser APIs (localStorage, matchMedia, ResizeObserver, canvas)
 *  2. Mock next/dynamic so dynamic imports render synchronously in tests
 *  3. Mock next/navigation (useRouter, usePathname, useSearchParams)
 *  4. Mock lightweight-charts
 *  5. Mock react-hot-toast
 *  6. Suppress React 18 act() warnings in test output
 *
 * NOTE: @testing-library/jest-dom and MSW lifecycle are in jest-globals-setup.ts
 *       which is imported by each test file since they need the test framework
 *       (expect, beforeAll, etc.) to be available.
 */

// ── Mock browser APIs not available in jsdom ─────────────────

// localStorage mock
const localStorageMock = (() => {
    let store: Record<string, string> = {};
    return {
        getItem: jest.fn((key: string) => store[key] ?? null),
        setItem: jest.fn((key: string, value: string) => {
            store[key] = value;
        }),
        removeItem: jest.fn((key: string) => {
            delete store[key];
        }),
        clear: jest.fn(() => {
            store = {};
        }),
        get length() {
            return Object.keys(store).length;
        },
        key: jest.fn((index: number) => Object.keys(store)[index] ?? null),
    };
})();

Object.defineProperty(window, "localStorage", { value: localStorageMock });

// matchMedia mock
Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: jest.fn().mockImplementation((query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addListener: jest.fn(),
        removeListener: jest.fn(),
        addEventListener: jest.fn(),
        removeEventListener: jest.fn(),
        dispatchEvent: jest.fn(),
    })),
});

// ResizeObserver mock
class ResizeObserverMock {
    observe = jest.fn();
    unobserve = jest.fn();
    disconnect = jest.fn();
}
(window as any).ResizeObserver = ResizeObserverMock;

// requestAnimationFrame / cancelAnimationFrame mock
let rafId = 0;
(window as any).requestAnimationFrame = (cb: FrameRequestCallback) => {
    const id = ++rafId;
    setTimeout(() => cb(Date.now()), 0);
    return id;
};
(window as any).cancelAnimationFrame = jest.fn();

// ── Mock next/dynamic – renders synchronously ────────────────

jest.mock("next/dynamic", () => {
    const React = require("react");
    return (dynamicImport: any, _options?: any) => {
        // Return a component that renders the loaded module
        const LazyComponent = React.lazy(dynamicImport);
        const DynamicComponent = (props: any) => {
            return React.createElement(
                React.Suspense,
                { fallback: null },
                React.createElement(LazyComponent, props),
            );
        };
        DynamicComponent.displayName = "DynamicMock";
        return DynamicComponent;
    };
});

// ── Mock next/navigation ─────────────────────────────────────

const mockRouter = {
    push: jest.fn(),
    replace: jest.fn(),
    back: jest.fn(),
    forward: jest.fn(),
    refresh: jest.fn(),
    prefetch: jest.fn(),
};

jest.mock("next/navigation", () => ({
    useRouter: () => mockRouter,
    usePathname: () => "/dashboard",
    useSearchParams: () => new URLSearchParams(),
    useParams: () => ({}),
}));

// ── Mock lightweight-charts (canvas-based, no DOM canvas) ────

jest.mock("lightweight-charts", () => ({
    createChart: jest.fn(() => ({
        addAreaSeries: jest.fn(() => ({
            setData: jest.fn(),
            update: jest.fn(),
        })),
        addLineSeries: jest.fn(() => ({
            setData: jest.fn(),
            update: jest.fn(),
        })),
        timeScale: jest.fn(() => ({
            fitContent: jest.fn(),
        })),
        applyOptions: jest.fn(),
        remove: jest.fn(),
        subscribeCrosshairMove: jest.fn(),
        unsubscribeCrosshairMove: jest.fn(),
    })),
    ColorType: {
        Solid: "solid",
        VerticalGradient: "vertical_gradient",
    },
}));

// ── Mock react-hot-toast ─────────────────────────────────────

jest.mock("react-hot-toast", () => {
    return {
        __esModule: true,
        default: {
            success: jest.fn(),
            error: jest.fn(),
            loading: jest.fn(),
            dismiss: jest.fn(),
            remove: jest.fn(),
        },
        Toaster: () => null,
        toast: {
            success: jest.fn(),
            error: jest.fn(),
            loading: jest.fn(),
            dismiss: jest.fn(),
            remove: jest.fn(),
        },
    };
});

// ── Suppress React 18 act() warnings (optional) ──────────────

const originalError = console.error;
console.error = (...args: any[]) => {
    if (
        typeof args[0] === "string" &&
        (args[0].includes("act(") || args[0].includes("inside a test was not wrapped in act"))
    ) {
        return;
    }
    originalError.call(console, ...args);
};