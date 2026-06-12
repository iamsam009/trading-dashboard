const nextJest = require("next/jest");

const createJestConfig = nextJest({
    dir: "./",
});

/** @type {import('jest').Config} */
const customJestConfig = {
    setupFiles: ["<rootDir>/__tests__/setup.ts"],
    testEnvironment: "<rootDir>/__tests__/jsdom-extended-env.ts",
    testEnvironmentOptions: {
        customExportConditions: [""],
    },
    moduleNameMapper: {
        "^@/(.*)$": "<rootDir>/src/$1",
        "\\.(css|less|scss|sass)$": "identity-obj-proxy",
        // MSW v2 `package.json` `imports` maps #core → ./src/core (TS source).
        // Jest resolves those to .ts files that import ESM-only .mjs deps.
        // Remap to the compiled CJS in lib/ instead.
        "^#core$": "<rootDir>/node_modules/msw/lib/core",
        "^#core/(.*)$": "<rootDir>/node_modules/msw/lib/core/$1",
        // MSW v2 also pulls in ESM-only sub-dependencies.
        // Jest+SWC cannot parse ESM; stub them with CJS equivalents.
        "^rettime$": "<rootDir>/__tests__/__mocks__/rettime-stub.js",
        "^until-async$": "<rootDir>/__tests__/__mocks__/until-async-stub.js",
        "^@open-draft/deferred-promise$": "<rootDir>/__tests__/__mocks__/deferred-promise-stub.js",
    },
    transformIgnorePatterns: [
        "/node_modules/(?!(lightweight-charts|recharts|msw|@mswjs|@bundled-es-modules|headers-polyfill|outvariant|strict-event-emitter|until-async|is-node-process|@open-draft)/)",
    ],
    testPathIgnorePatterns: [
        "<rootDir>/node_modules/",
        "<rootDir>/.next/",
    ],
    testMatch: [
        "<rootDir>/__tests__/**/*.test.[jt]s?(x)",
    ],
    collectCoverageFrom: [
        "src/components/Dashboard/PositionsTable.tsx",
        "src/components/Dashboard/TradeHistory.tsx",
        "src/components/Strategy/StrategyRunner.tsx",
        "src/components/RiskPanel.tsx",
        "src/hooks/useWebSocket.ts",
    ],
    coverageThreshold: {
        global: {
            branches: 70,
            functions: 80,
            lines: 80,
            statements: 80,
        },
    },
};

module.exports = createJestConfig(customJestConfig);