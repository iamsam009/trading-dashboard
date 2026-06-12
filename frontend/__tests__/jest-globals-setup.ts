/**
 * Jest globals setup – imported at the top of each test file.
 *
 * The custom test environment (jsdom-extended-env.ts) injects
 * Request/Response/Headers/fetch into the jsdom global, so MSW v2
 * can initialize without errors.
 *
 * Responsibilities:
 *  1. Load @testing-library/jest-dom matchers (toBeInTheDocument, toHaveValue, etc.)
 *  2. Start/stop MSW server lifecycle
 *
 * NOTE: This must be imported by each test file because it requires the test
 *       framework (expect, beforeAll, etc.) to be available. In Jest 30+,
 *       setupFiles runs before the framework, so we cannot use it for these.
 */

// Use require() to avoid ES module import hoisting.
// eslint-disable-next-line @typescript-eslint/no-require-imports
require("@testing-library/jest-dom");

// eslint-disable-next-line @typescript-eslint/no-require-imports
const { server } = require("./mocks/server");

// ── MSW lifecycle ────────────────────────────────────────────

beforeAll(() => server.listen({ onUnhandledRequest: "bypass" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());